from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pupu_assistant.domain.assistant_cart.models import ProductSnapshot
from pupu_assistant.domain.assistant_cart.service import AssistantCart
from pupu_assistant.domain.cart_write import (
    MaterialCartChange,
    PlatformCartState,
    build_cart_preview,
    validate_preview,
)

NOW = datetime(2026, 7, 21, 4, 0, tzinfo=UTC)


def product(*, price: str = "12.50", stock: bool = True) -> ProductSnapshot:
    return ProductSnapshot(
        product_id="p1",
        sku_id="sku-p1",
        name="Fresh milk",
        specification="500 ml",
        unit_price=Decimal(price),
        stock_available=stock,
        store_id="s1",
        captured_at=NOW,
        source="pupu",
    )


def test_preview_binds_cart_version_prices_quantities_store_and_expiry() -> None:
    cart = AssistantCart(store_id="s1").add(
        product(), quantity=2, operation_id="add-milk"
    )
    state = PlatformCartState(
        store_id="s1",
        products=(product(),),
        quantities={"p1": 1},
    )

    preview = build_cart_preview(
        cart,
        state,
        now=NOW,
        ttl=timedelta(minutes=5),
        confirmation_id="confirm-1",
        idempotency_key="idem-1",
    )

    assert preview.assistant_cart_version == 1
    assert preview.store_id == "s1"
    assert preview.expires_at == NOW + timedelta(minutes=5)
    assert preview.operations[0].before_quantity == 1
    assert preview.operations[0].target_quantity == 2
    assert preview.operations[0].estimated_delta == Decimal("12.50")
    assert len(preview.preview_hash) == 64


@pytest.mark.parametrize(
    "changed_state",
    [
        PlatformCartState(
            store_id="s2", products=(product(),), quantities={"p1": 1}
        ),
        PlatformCartState(
            store_id="s1", products=(product(price="13.00"),), quantities={"p1": 1}
        ),
        PlatformCartState(
            store_id="s1", products=(product(stock=False),), quantities={"p1": 1}
        ),
        PlatformCartState(
            store_id="s1", products=(product(),), quantities={"p1": 2}
        ),
    ],
)
def test_store_price_stock_or_cart_change_invalidates_preview(
    changed_state: PlatformCartState,
) -> None:
    cart = AssistantCart(store_id="s1").add(
        product(), quantity=2, operation_id="add-milk"
    )
    original = PlatformCartState(
        store_id="s1", products=(product(),), quantities={"p1": 1}
    )
    preview = build_cart_preview(
        cart,
        original,
        now=NOW,
        ttl=timedelta(minutes=5),
        confirmation_id="confirm-1",
        idempotency_key="idem-1",
    )

    with pytest.raises(MaterialCartChange):
        validate_preview(preview, changed_state)
