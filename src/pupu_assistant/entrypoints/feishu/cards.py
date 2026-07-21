from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pupu_assistant.domain.purchase.session import PurchaseSessionSnapshot


type FeishuCardPayload = dict[str, object]


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


def render_assistant_cart_card(
    view: AssistantCartCardView,
) -> FeishuCardPayload:
    """Render a Card 2.0 payload without sending it to Feishu."""

    elements: list[dict[str, object]] = []
    for item in view.items:
        elements.extend(_render_cart_item(view, item))

    if not view.items:
        elements.append(
            {
                "tag": "markdown",
                "content": "助手购物车当前为空。",
                "text_size": "normal",
            }
        )

    elements.append(
        {
            "tag": "markdown",
            "content": f"**预计合计：¥{view.estimated_total:.2f}**",
            "text_size": "normal",
        }
    )
    elements.append(
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "确认采购方案"},
            "type": "primary",
            "width": "fill",
            "disabled": not view.can_confirm,
            "behaviors": [
                {
                    "type": "callback",
                    "value": _action_value(view, CartCardAction.CONFIRM),
                }
            ],
        }
    )
    elements.append(
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "取消当前采购"},
            "type": "default",
            "width": "fill",
            "behaviors": [
                {
                    "type": "callback",
                    "value": _action_value(view, CartCardAction.CANCEL),
                }
            ],
        }
    )
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": view.title},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": elements,
        },
    }


def _render_cart_item(
    view: AssistantCartCardView,
    item: AssistantCartCardItem,
) -> list[dict[str, object]]:
    stock_text = "有货" if item.stock_available else "库存不足"
    elements: list[dict[str, object]] = [
        {
            "tag": "markdown",
            "content": (
                f"**{_escape_markdown(item.product_name)}**\n"
                f"{_escape_markdown(item.specification)}｜¥{item.unit_price:.2f} × "
                f"{item.quantity}｜小计 ¥{item.subtotal:.2f}｜{stock_text}"
            ),
            "text_size": "normal",
        }
    ]
    if item.quantity > 1:
        elements.append(
            _action_button(
                text="减少 1 件",
                value=_action_value(
                    view,
                    CartCardAction.SET_QUANTITY,
                    product_id=item.product_id,
                    quantity=item.quantity - 1,
                ),
            )
        )
    elements.append(
        _action_button(
            text="增加 1 件",
            value=_action_value(
                view,
                CartCardAction.SET_QUANTITY,
                product_id=item.product_id,
                quantity=item.quantity + 1,
            ),
        )
    )
    elements.append(
        _action_button(
            text="删除",
            value=_action_value(
                view,
                CartCardAction.REMOVE,
                product_id=item.product_id,
            ),
            button_type="danger",
        )
    )
    elements.append({"tag": "hr"})
    return elements


def _action_button(
    *,
    text: str,
    value: dict[str, object],
    button_type: str = "default",
) -> dict[str, object]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": button_type,
        "width": "fill",
        "behaviors": [{"type": "callback", "value": value}],
    }


def _action_value(
    view: AssistantCartCardView,
    action: CartCardAction,
    *,
    product_id: str | None = None,
    quantity: int | None = None,
) -> dict[str, object]:
    value = CartCardActionValue(
        action=action,
        task_id=view.task_id,
        cart_version=view.cart_version,
        product_id=product_id,
        quantity=quantity,
    )
    return value.model_dump(mode="json", exclude_none=True)


def _escape_markdown(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for marker in ("`", "*", "_", "[", "]", "~"):
        escaped = escaped.replace(marker, f"\\{marker}")
    return escaped
