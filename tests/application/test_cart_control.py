from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pupu_assistant.application.cart_control import (
    CartControl,
    CartExecutionStatus,
    LiveMutationDisabled,
)
from pupu_assistant.domain.assistant_cart.models import ProductSnapshot
from pupu_assistant.domain.assistant_cart.service import AssistantCart
from pupu_assistant.domain.cart_write import (
    CartMutationTimeout,
    PlatformCartState,
    build_cart_preview,
)
from pupu_assistant.storage.confirmation_store import ConfirmationStore

NOW = datetime(2026, 7, 21, 4, 0, tzinfo=UTC)


def product() -> ProductSnapshot:
    return ProductSnapshot(
        product_id="p1",
        sku_id="sku-p1",
        name="Fresh milk",
        specification="500 ml",
        unit_price=Decimal("12.50"),
        stock_available=True,
        store_id="s1",
        captured_at=NOW,
        source="pupu",
    )


def make_preview():
    cart = AssistantCart(store_id="s1").add(
        product(), quantity=1, operation_id="add"
    )
    return build_cart_preview(
        cart,
        PlatformCartState(store_id="s1", products=(product(),), quantities={}),
        now=NOW,
        ttl=timedelta(minutes=5),
        confirmation_id="confirm-1",
        idempotency_key="idem-1",
    )


class FakeGateway:
    def __init__(self, *, timeout_after_write: bool = False, timeout_before_write: bool = False):
        self.quantities: dict[str, int] = {}
        self.timeout_after_write = timeout_after_write
        self.timeout_before_write = timeout_before_write
        self.mutations = 0

    async def read_state(self, product_ids: set[str]) -> PlatformCartState:
        assert product_ids == {"p1"}
        return PlatformCartState(
            store_id="s1",
            products=(product(),),
            quantities=dict(self.quantities),
        )

    async def set_absolute_quantities(self, operations, *, idempotency_key: str) -> None:
        assert idempotency_key == "idem-1"
        self.mutations += 1
        if self.timeout_before_write:
            raise CartMutationTimeout("unknown before response")
        self.quantities.update(
            {operation.product_id: operation.target_quantity for operation in operations}
        )
        if self.timeout_after_write:
            raise CartMutationTimeout("unknown after write")


@pytest.mark.asyncio
async def test_live_switch_blocks_before_network_or_consuming_confirmation(tmp_path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.json")
    store.put(make_preview())
    gateway = FakeGateway()
    control = CartControl(gateway=gateway, confirmations=store, live_mutation_allowed=False)

    with pytest.raises(LiveMutationDisabled):
        await control.execute(
            "confirm-1",
            phrase="确认同步到朴朴购物车",
            now=NOW,
        )

    assert gateway.mutations == 0
    assert store.get("confirm-1").used_at is None


@pytest.mark.asyncio
async def test_success_requires_matching_cart_readback(tmp_path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.json")
    store.put(make_preview())
    gateway = FakeGateway()
    control = CartControl(gateway=gateway, confirmations=store, live_mutation_allowed=True)

    result = await control.execute(
        "confirm-1",
        phrase="确认同步到朴朴购物车",
        now=NOW,
    )

    assert result.status is CartExecutionStatus.VERIFIED
    assert result.quantities == {"p1": 1}
    assert gateway.mutations == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gateway", "expected"),
    [
        (FakeGateway(timeout_after_write=True), CartExecutionStatus.VERIFIED),
        (FakeGateway(timeout_before_write=True), CartExecutionStatus.UNKNOWN),
    ],
)
async def test_timeout_is_resolved_by_readback_without_retry(
    tmp_path,
    gateway: FakeGateway,
    expected: CartExecutionStatus,
) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.json")
    store.put(make_preview())
    control = CartControl(gateway=gateway, confirmations=store, live_mutation_allowed=True)

    result = await control.execute(
        "confirm-1",
        phrase="确认同步到朴朴购物车",
        now=NOW,
    )

    assert result.status is expected
    assert gateway.mutations == 1
