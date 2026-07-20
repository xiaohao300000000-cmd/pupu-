from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from pupu_assistant.domain.assistant_cart.models import ProductSnapshot
from pupu_assistant.domain.assistant_cart.service import AssistantCart

CONFIRMATION_PHRASE = "确认同步到朴朴购物车"


class MaterialCartChange(RuntimeError):
    pass


class CartMutationTimeout(RuntimeError):
    """Mutation outcome is unknown and must be resolved by a cart read."""


class CartWriteOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str = Field(min_length=1)
    sku_id: str | None = None
    name: str = Field(min_length=1)
    specification: str = Field(min_length=1)
    before_quantity: int = Field(ge=0)
    target_quantity: int = Field(ge=0)
    unit_price: Decimal = Field(ge=0)
    stock_available: bool
    captured_at: datetime

    @property
    def estimated_delta(self) -> Decimal:
        return self.unit_price * (self.target_quantity - self.before_quantity)


class PlatformCartState(BaseModel):
    model_config = ConfigDict(frozen=True)

    store_id: str = Field(min_length=1)
    products: tuple[ProductSnapshot, ...]
    quantities: dict[str, int]

    def product_map(self) -> dict[str, ProductSnapshot]:
        return {product.product_id: product for product in self.products}


class CartPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    confirmation_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    assistant_cart_version: int = Field(ge=1)
    store_id: str = Field(min_length=1)
    operations: tuple[CartWriteOperation, ...] = Field(min_length=1)
    created_at: datetime
    expires_at: datetime
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        confirmation_id: str,
        idempotency_key: str,
        assistant_cart_version: int,
        store_id: str,
        operations: tuple[CartWriteOperation, ...],
        created_at: datetime,
        expires_at: datetime,
    ) -> CartPreview:
        values = {
            "confirmation_id": confirmation_id,
            "idempotency_key": idempotency_key,
            "assistant_cart_version": assistant_cart_version,
            "store_id": store_id,
            "operations": operations,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        preview_hash = _hash_payload(values)
        return cls(**values, preview_hash=preview_hash)

    def calculated_hash(self) -> str:
        return _hash_payload(self.model_dump(exclude={"preview_hash"}))


def build_cart_preview(
    cart: AssistantCart,
    state: PlatformCartState,
    *,
    now: datetime,
    ttl: timedelta,
    confirmation_id: str,
    idempotency_key: str,
) -> CartPreview:
    if ttl <= timedelta(0):
        raise ValueError("Preview TTL must be positive")
    if cart.store_id != state.store_id:
        raise MaterialCartChange("Current store differs from assistant cart store")
    current_products = state.product_map()
    operations: list[CartWriteOperation] = []
    for item in cart.items:
        current = current_products.get(item.product.product_id)
        if current is None:
            raise MaterialCartChange(
                f"Product is missing from current platform state: {item.product.product_id}"
            )
        _validate_product_snapshot(item.product, current)
        operations.append(
            CartWriteOperation(
                product_id=current.product_id,
                sku_id=current.sku_id,
                name=current.name,
                specification=current.specification,
                before_quantity=state.quantities.get(current.product_id, 0),
                target_quantity=item.quantity,
                unit_price=current.unit_price,
                stock_available=current.stock_available,
                captured_at=current.captured_at,
            )
        )
    if not operations:
        raise ValueError("Cannot create a cart preview without operations")
    return CartPreview.create(
        confirmation_id=confirmation_id,
        idempotency_key=idempotency_key,
        assistant_cart_version=cart.version,
        store_id=cart.store_id,
        operations=tuple(operations),
        created_at=now,
        expires_at=now + ttl,
    )


def validate_preview(preview: CartPreview, state: PlatformCartState) -> None:
    if preview.store_id != state.store_id:
        raise MaterialCartChange("Store changed after confirmation preview")
    current_products = state.product_map()
    for operation in preview.operations:
        current = current_products.get(operation.product_id)
        if current is None:
            raise MaterialCartChange(f"Product disappeared: {operation.product_id}")
        if current.sku_id != operation.sku_id:
            raise MaterialCartChange(f"Product SKU changed: {operation.product_id}")
        if current.unit_price != operation.unit_price:
            raise MaterialCartChange(f"Product price changed: {operation.product_id}")
        if current.stock_available != operation.stock_available or not current.stock_available:
            raise MaterialCartChange(f"Product stock changed: {operation.product_id}")
        if state.quantities.get(operation.product_id, 0) != operation.before_quantity:
            raise MaterialCartChange(
                f"Current cart quantity changed: {operation.product_id}"
            )


def _validate_product_snapshot(
    planned: ProductSnapshot,
    current: ProductSnapshot,
) -> None:
    if (
        planned.sku_id != current.sku_id
        or planned.unit_price != current.unit_price
        or planned.stock_available != current.stock_available
        or not current.stock_available
    ):
        raise MaterialCartChange(f"Product changed: {planned.product_id}")


def _hash_payload(payload: object) -> str:
    if isinstance(payload, dict):
        normalized = {
            key: _json_value(value)
            for key, value in payload.items()
        }
    else:
        normalized = _json_value(payload)
    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump())
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value
