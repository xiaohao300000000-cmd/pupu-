from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from pupu_assistant.domain.assistant_cart.models import ProductSnapshot
from pupu_assistant.domain.cart_write import (
    CartWriteOperation,
    PlatformCartState,
)


class PupuConnectorError(RuntimeError):
    pass


class PupuConnectorContractViolation(PupuConnectorError):
    pass


class PupuConnectorUnavailable(PupuConnectorError):
    pass


class PupuConnectorAuthenticationRequired(PupuConnectorError):
    pass


class PupuConnectorCapabilityUnavailable(PupuConnectorError):
    pass


class AddressSummary(BaseModel):
    """An address selector without a full door number or raw address payload."""

    model_config = ConfigDict(frozen=True)

    address_id: str = Field(min_length=1)
    display_label: str = Field(min_length=1)
    is_default: bool = False


class ProductFilters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_price: Decimal | None = Field(default=None, ge=0)
    preferred_brands: tuple[str, ...] = ()
    excluded_brands: tuple[str, ...] = ()
    in_stock_only: bool = True


class OrderSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    created_at: datetime
    total_amount: Decimal = Field(ge=0)
    item_count: int = Field(ge=0)


class OrderItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str = Field(min_length=1)
    store_product_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    specification: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    purchased_unit_price: Decimal = Field(ge=0)
    activity_label: str | None = None


class OrderDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    order: OrderSummary
    items: tuple[OrderItem, ...]


class ProductCheckStatus(StrEnum):
    AVAILABLE = "available"
    OUT_OF_STOCK = "out_of_stock"
    PRICE_CHANGED = "price_changed"
    UNAVAILABLE = "unavailable"


class ProductCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    requested_product_id: str = Field(min_length=1)
    status: ProductCheckStatus
    current_product: ProductSnapshot | None = None
    reason: str = Field(min_length=1)


class StoreContext(BaseModel):
    """Non-sensitive store facts safe to expose to the purchase Agent."""

    model_config = ConfigDict(frozen=True)

    address_id: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    place_id: str = Field(min_length=1)
    city_zip: str = Field(min_length=1)
    display_name: str | None = None


class PupuConnector(Protocol):
    """Stable platform boundary; implementations keep credentials private."""

    async def authenticate(self, *, user_id: str) -> None: ...

    async def get_addresses(self, *, user_id: str) -> Sequence[AddressSummary]: ...

    async def resolve_store(
        self,
        *,
        user_id: str,
        address_id: str,
    ) -> StoreContext: ...

    async def get_current_store(self, *, user_id: str) -> StoreContext: ...

    async def search_products(
        self,
        *,
        user_id: str,
        query: str,
        store_id: str,
        limit: int,
        filters: ProductFilters | None = None,
    ) -> Sequence[ProductSnapshot]: ...

    async def get_product_detail(
        self,
        *,
        user_id: str,
        store_id: str,
        store_product_id: str,
    ) -> ProductSnapshot: ...

    async def get_favorite_products(
        self,
        *,
        user_id: str,
        store_id: str,
        page: int,
        page_size: int,
    ) -> Sequence[ProductSnapshot]: ...

    async def get_orders(
        self,
        *,
        user_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Sequence[OrderSummary]: ...

    async def get_order_detail(
        self,
        *,
        user_id: str,
        order_id: str,
    ) -> OrderDetail: ...

    async def get_current_cart(self, *, user_id: str) -> PlatformCartState: ...

    async def check_price_and_stock(
        self,
        *,
        user_id: str,
        store_id: str,
        products: Sequence[ProductSnapshot],
    ) -> Sequence[ProductCheckResult]: ...

    async def find_platform_substitutes(
        self,
        *,
        user_id: str,
        store_id: str,
        product: ProductSnapshot,
        filters: ProductFilters | None = None,
        limit: int = 3,
    ) -> Sequence[ProductSnapshot]: ...

    async def add_cart_items(
        self,
        *,
        user_id: str,
        operations: Sequence[CartWriteOperation],
        idempotency_key: str,
    ) -> None: ...
