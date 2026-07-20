import pytest

from pupu_assistant.application.state_machine import (
    InvalidPurchaseTransition,
    PurchaseState,
    PurchaseStateMachine,
)


def build_cart_ready_machine() -> PurchaseStateMachine:
    machine = PurchaseStateMachine()
    machine.start_understanding()
    machine.gather_context()
    machine.begin_search()
    machine.begin_cart_build()
    machine.cart_changed(version=1)
    machine.request_confirmation()
    return machine


def test_real_cart_write_tool_is_exposed_only_after_confirmed_revalidation() -> None:
    machine = build_cart_ready_machine()

    assert machine.state is PurchaseState.AWAITING_CONFIRMATION
    assert "execute_cart_sync" not in machine.allowed_tools()

    machine.confirm(confirmation_id="confirm-1", cart_version=1)
    assert machine.state is PurchaseState.REVALIDATING
    assert "execute_cart_sync" not in machine.allowed_tools()

    machine.revalidation_complete(material_change=False)
    assert machine.state is PurchaseState.SYNCING
    assert machine.allowed_tools() == {"execute_cart_sync"}


def test_material_change_requires_a_new_confirmation() -> None:
    machine = build_cart_ready_machine()
    machine.confirm(confirmation_id="confirm-1", cart_version=1)

    machine.revalidation_complete(material_change=True)

    assert machine.state is PurchaseState.AWAITING_RECONFIRMATION
    assert machine.confirmation_id is None
    assert machine.confirmed_cart_version is None
    assert "execute_cart_sync" not in machine.allowed_tools()


def test_cart_change_invalidates_an_existing_confirmation() -> None:
    machine = build_cart_ready_machine()
    machine.confirm(confirmation_id="confirm-1", cart_version=1)

    machine.cart_changed(version=2)

    assert machine.state is PurchaseState.BUILDING_CART
    assert machine.cart_version == 2
    assert machine.confirmation_id is None
    assert machine.confirmed_cart_version is None


def test_confirmation_must_match_the_current_cart_version() -> None:
    machine = build_cart_ready_machine()

    with pytest.raises(InvalidPurchaseTransition, match="cart version"):
        machine.confirm(confirmation_id="confirm-old", cart_version=0)


def test_success_requires_write_followed_by_matching_readback() -> None:
    machine = build_cart_ready_machine()
    machine.confirm(confirmation_id="confirm-1", cart_version=1)
    machine.revalidation_complete(material_change=False)
    machine.write_returned()

    assert machine.state is PurchaseState.VERIFYING
    assert machine.allowed_tools() == {"get_current_cart"}

    machine.verification_complete(matches=True)
    assert machine.state is PurchaseState.COMPLETED


def test_state_machine_rejects_skipping_directly_to_cart_build() -> None:
    machine = PurchaseStateMachine()

    with pytest.raises(InvalidPurchaseTransition):
        machine.begin_cart_build()
