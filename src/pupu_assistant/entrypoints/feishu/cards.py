from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pupu_assistant.domain.purchase.session import PurchaseSessionSnapshot


class CartCardAction(StrEnum):
    SET_QUANTITY = "set_quantity"
    REMOVE = "remove"
    CONFIRM = "confirm"
    CANCEL = "cancel"


class CartCardActionValue(BaseModel):
    """Business value embedded in a Feishu card component callback."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: CartCardAction
    task_id: str = Field(min_length=1)
    cart_version: int = Field(ge=0)
    product_id: str | None = None
    quantity: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_action_fields(self) -> CartCardActionValue:
        if self.action in {CartCardAction.SET_QUANTITY, CartCardAction.REMOVE}:
            if not self.product_id:
                raise ValueError("cart item action requires product_id")
        if self.action is CartCardAction.SET_QUANTITY and self.quantity is None:
            raise ValueError("set_quantity action requires quantity")
        return self


class AssistantCartCardItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    product_name: str
    specification: str
    unit_price: Decimal
    quantity: int
    subtotal: Decimal
    stock_available: bool


class AssistantCartCardView(BaseModel):
    """Transport-neutral content for a Feishu Card 2.0 renderer."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    cart_version: int
    title: str
    items: tuple[AssistantCartCardItem, ...]
    estimated_total: Decimal
    can_confirm: bool

    @classmethod
    def from_session(
        cls, snapshot: PurchaseSessionSnapshot
    ) -> AssistantCartCardView:
        if snapshot.cart is None:
            raise ValueError("purchase session has no assistant cart")
        return cls(
            task_id=snapshot.task_id,
            cart_version=snapshot.cart.version,
            title="采购方案待确认",
            items=tuple(
                AssistantCartCardItem(
                    product_id=item.product.product_id,
                    product_name=item.product.name,
                    specification=item.product.specification,
                    unit_price=item.product.unit_price,
                    quantity=item.quantity,
                    subtotal=item.estimated_subtotal,
                    stock_available=item.product.stock_available,
                )
                for item in snapshot.cart.items
            ),
            estimated_total=snapshot.cart.estimated_total,
            can_confirm=bool(snapshot.cart.items),
        )
