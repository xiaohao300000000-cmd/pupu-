from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pupu_assistant.domain.assistant_cart.models import ProductSnapshot
from pupu_assistant.domain.assistant_cart.service import (
    AssistantCart,
    CartStoreMismatch,
)


def product(product_id: str = "p1", *, store_id: str = "s1") -> ProductSnapshot:
    return ProductSnapshot(
        product_id=product_id,
        sku_id=f"sku-{product_id}",
        name=f"Product {product_id}",
        specification="500 ml",
        unit_price=Decimal("12.50"),
        stock_available=True,
        store_id=store_id,
        captured_at=datetime(2026, 7, 21, tzinfo=UTC),
        source="pupu",
    )


def test_cart_add_is_versioned_and_operation_is_idempotent() -> None:
    cart = AssistantCart(store_id="s1")

    first = cart.add(product(), quantity=1, operation_id="op-1")
    repeated = first.add(product(), quantity=1, operation_id="op-1")
    second = repeated.add(product(), quantity=2, operation_id="op-2")

    assert first.version == 1
    assert repeated == first
    assert second.version == 2
    assert second.items[0].quantity == 3
    assert second.estimated_total == Decimal("37.50")


def test_cart_edit_remove_and_replace_each_create_a_new_version() -> None:
    cart = AssistantCart(store_id="s1").add(
        product("p1"), quantity=2, operation_id="add"
    )

    edited = cart.set_quantity("p1", quantity=3, operation_id="edit")
    replaced = edited.replace(
        "p1",
        product("p2"),
        operation_id="replace",
    )
    removed = replaced.remove("p2", operation_id="remove")

    assert edited.version == 2
    assert edited.items[0].quantity == 3
    assert replaced.version == 3
    assert replaced.items[0].product.product_id == "p2"
    assert replaced.items[0].quantity == 3
    assert removed.version == 4
    assert removed.items == ()


def test_cart_rejects_product_from_a_different_store() -> None:
    cart = AssistantCart(store_id="s1")

    with pytest.raises(CartStoreMismatch):
        cart.add(product(store_id="s2"), quantity=1, operation_id="wrong-store")
