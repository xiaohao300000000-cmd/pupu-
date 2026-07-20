from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from pupu_assistant.domain.assistant_cart.models import (
    AssistantCartItem,
    ProductSnapshot,
)


class AssistantCartError(RuntimeError):
    pass


class CartStoreMismatch(AssistantCartError):
    pass


class ProductNotInCart(AssistantCartError):
    pass


class AssistantCart(BaseModel):
    """Immutable, versioned plan; this object never writes the real platform cart."""

    model_config = ConfigDict(frozen=True)

    store_id: str = Field(min_length=1)
    version: int = Field(default=0, ge=0)
    items: tuple[AssistantCartItem, ...] = ()
    applied_operation_ids: tuple[str, ...] = ()

    @property
    def estimated_total(self) -> Decimal:
        return sum(
            (item.estimated_subtotal for item in self.items),
            start=Decimal("0"),
        )

    def add(
        self,
        product: ProductSnapshot,
        *,
        quantity: int,
        operation_id: str,
    ) -> AssistantCart:
        if self._already_applied(operation_id):
            return self
        self._require_product_store(product)
        self._require_quantity(quantity)
        items = list(self.items)
        for index, item in enumerate(items):
            if item.product.product_id == product.product_id:
                items[index] = AssistantCartItem(
                    product=product,
                    quantity=item.quantity + quantity,
                )
                break
        else:
            items.append(AssistantCartItem(product=product, quantity=quantity))
        return self._next(items, operation_id)

    def set_quantity(
        self,
        product_id: str,
        *,
        quantity: int,
        operation_id: str,
    ) -> AssistantCart:
        if self._already_applied(operation_id):
            return self
        self._require_quantity(quantity)
        items = list(self.items)
        for index, item in enumerate(items):
            if item.product.product_id == product_id:
                items[index] = AssistantCartItem(
                    product=item.product,
                    quantity=quantity,
                )
                return self._next(items, operation_id)
        raise ProductNotInCart(f"Product is not in assistant cart: {product_id}")

    def remove(self, product_id: str, *, operation_id: str) -> AssistantCart:
        if self._already_applied(operation_id):
            return self
        items = [
            item for item in self.items if item.product.product_id != product_id
        ]
        if len(items) == len(self.items):
            raise ProductNotInCart(f"Product is not in assistant cart: {product_id}")
        return self._next(items, operation_id)

    def replace(
        self,
        product_id: str,
        replacement: ProductSnapshot,
        *,
        operation_id: str,
    ) -> AssistantCart:
        if self._already_applied(operation_id):
            return self
        self._require_product_store(replacement)
        items = list(self.items)
        for index, item in enumerate(items):
            if item.product.product_id == product_id:
                items[index] = AssistantCartItem(
                    product=replacement,
                    quantity=item.quantity,
                )
                return self._next(items, operation_id)
        raise ProductNotInCart(f"Product is not in assistant cart: {product_id}")

    def _already_applied(self, operation_id: str) -> bool:
        if not operation_id:
            raise ValueError("operation_id cannot be empty")
        return operation_id in self.applied_operation_ids

    def _require_product_store(self, product: ProductSnapshot) -> None:
        if product.store_id != self.store_id:
            raise CartStoreMismatch(
                "Assistant cart and product must belong to the same store"
            )

    @staticmethod
    def _require_quantity(quantity: int) -> None:
        if quantity < 1:
            raise ValueError("quantity must be at least one")

    def _next(
        self,
        items: list[AssistantCartItem],
        operation_id: str,
    ) -> AssistantCart:
        return AssistantCart(
            store_id=self.store_id,
            version=self.version + 1,
            items=tuple(items),
            applied_operation_ids=(*self.applied_operation_ids, operation_id),
        )
