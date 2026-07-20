import stat
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pupu_assistant.domain.cart_write import CartPreview, CartWriteOperation
from pupu_assistant.storage.confirmation_store import (
    ConfirmationExpired,
    ConfirmationPhraseMismatch,
    ConfirmationStore,
    ConfirmationUsed,
)

NOW = datetime(2026, 7, 21, 4, 0, tzinfo=UTC)


def preview() -> CartPreview:
    operation = CartWriteOperation(
        product_id="p1",
        sku_id="sku-p1",
        name="Fresh milk",
        specification="500 ml",
        before_quantity=0,
        target_quantity=1,
        unit_price=Decimal("12.50"),
        stock_available=True,
        captured_at=NOW,
    )
    return CartPreview.create(
        confirmation_id="confirm-1",
        idempotency_key="idem-1",
        assistant_cart_version=1,
        store_id="s1",
        operations=(operation,),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def test_confirmation_file_is_private_and_confirmation_is_one_time(tmp_path) -> None:
    path = tmp_path / "confirmations.json"
    store = ConfirmationStore(path)
    store.put(preview())

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    consumed = store.consume(
        "confirm-1",
        phrase="确认同步到朴朴购物车",
        now=NOW + timedelta(minutes=1),
    )
    assert consumed.confirmation_id == "confirm-1"

    with pytest.raises(ConfirmationUsed):
        store.consume(
            "confirm-1",
            phrase="确认同步到朴朴购物车",
            now=NOW + timedelta(minutes=2),
        )


def test_confirmation_requires_exact_phrase_and_must_not_be_expired(tmp_path) -> None:
    store = ConfirmationStore(tmp_path / "confirmations.json")
    store.put(preview())

    with pytest.raises(ConfirmationPhraseMismatch):
        store.consume("confirm-1", phrase="confirm", now=NOW)

    with pytest.raises(ConfirmationExpired):
        store.consume(
            "confirm-1",
            phrase="确认同步到朴朴购物车",
            now=NOW + timedelta(minutes=6),
        )
