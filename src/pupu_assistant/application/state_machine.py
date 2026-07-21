from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PurchaseState(StrEnum):
    RECEIVED = "received"
    UNDERSTANDING = "understanding"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    GATHERING_CONTEXT = "gathering_context"
    SEARCHING = "searching"
    BUILDING_CART = "building_cart"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    REVALIDATING = "revalidating"
    AWAITING_RECONFIRMATION = "awaiting_reconfirmation"
    SYNCING = "syncing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AUTH_REQUIRED = "auth_required"


class InvalidPurchaseTransition(RuntimeError):
    pass


READ_CONTEXT_TOOLS = {
    "get_current_store",
    "get_current_cart",
    "get_orders",
    "get_favorite_products",
}
SEARCH_TOOLS = {
    "search_products",
    "get_product_detail",
    "check_price_and_stock",
    "find_platform_substitutes",
}
ASSISTANT_CART_TOOLS = {
    "assistant_cart.get",
    "assistant_cart.add",
    "assistant_cart.set_quantity",
    "assistant_cart.remove",
    "assistant_cart.replace",
}


@dataclass
class PurchaseStateMachine:
    state: PurchaseState = PurchaseState.RECEIVED
    cart_version: int = 0
    confirmation_id: str | None = None
    confirmed_cart_version: int | None = None

    def start_understanding(self) -> None:
        self._transition(PurchaseState.UNDERSTANDING, from_states={PurchaseState.RECEIVED})

    def await_clarification(self) -> None:
        self._transition(
            PurchaseState.AWAITING_CLARIFICATION,
            from_states={PurchaseState.UNDERSTANDING},
        )

    def resume_understanding(self) -> None:
        self._transition(
            PurchaseState.UNDERSTANDING,
            from_states={PurchaseState.AWAITING_CLARIFICATION},
        )

    def gather_context(self) -> None:
        self._transition(
            PurchaseState.GATHERING_CONTEXT,
            from_states={
                PurchaseState.UNDERSTANDING,
                PurchaseState.AWAITING_CLARIFICATION,
            },
        )

    def begin_search(self) -> None:
        self._transition(
            PurchaseState.SEARCHING,
            from_states={PurchaseState.GATHERING_CONTEXT},
        )

    def begin_cart_build(self) -> None:
        self._transition(
            PurchaseState.BUILDING_CART,
            from_states={PurchaseState.SEARCHING},
        )

    def cart_changed(self, *, version: int) -> None:
        if self.state not in {
            PurchaseState.BUILDING_CART,
            PurchaseState.AWAITING_CONFIRMATION,
            PurchaseState.AWAITING_RECONFIRMATION,
            PurchaseState.REVALIDATING,
        }:
            raise InvalidPurchaseTransition(
                f"Cannot change cart while state is {self.state}"
            )
        if version <= self.cart_version:
            raise InvalidPurchaseTransition("New cart version must increase")
        self.cart_version = version
        self.confirmation_id = None
        self.confirmed_cart_version = None
        self.state = PurchaseState.BUILDING_CART

    def request_confirmation(self) -> None:
        if self.cart_version < 1:
            raise InvalidPurchaseTransition("Cannot confirm an empty cart version")
        self._transition(
            PurchaseState.AWAITING_CONFIRMATION,
            from_states={PurchaseState.BUILDING_CART},
        )

    def confirm(self, *, confirmation_id: str, cart_version: int) -> None:
        if self.state not in {
            PurchaseState.AWAITING_CONFIRMATION,
            PurchaseState.AWAITING_RECONFIRMATION,
        }:
            raise InvalidPurchaseTransition(
                f"Cannot confirm while state is {self.state}"
            )
        if cart_version != self.cart_version:
            raise InvalidPurchaseTransition("Confirmation cart version is stale")
        if not confirmation_id:
            raise InvalidPurchaseTransition("confirmation_id cannot be empty")
        self.confirmation_id = confirmation_id
        self.confirmed_cart_version = cart_version
        self.state = PurchaseState.REVALIDATING

    def revalidation_complete(self, *, material_change: bool) -> None:
        if self.state is not PurchaseState.REVALIDATING:
            raise InvalidPurchaseTransition(
                f"Cannot finish revalidation while state is {self.state}"
            )
        if material_change:
            self.confirmation_id = None
            self.confirmed_cart_version = None
            self.state = PurchaseState.AWAITING_RECONFIRMATION
        else:
            self.state = PurchaseState.SYNCING

    def write_returned(self) -> None:
        self._transition(
            PurchaseState.VERIFYING,
            from_states={PurchaseState.SYNCING},
        )

    def verification_complete(self, *, matches: bool) -> None:
        self._transition(
            PurchaseState.COMPLETED if matches else PurchaseState.PARTIAL_FAILED,
            from_states={PurchaseState.VERIFYING},
        )

    def cancel(self) -> None:
        if self.state in {
            PurchaseState.COMPLETED,
            PurchaseState.PARTIAL_FAILED,
            PurchaseState.FAILED,
            PurchaseState.CANCELLED,
        }:
            raise InvalidPurchaseTransition(
                f"Cannot cancel while state is {self.state}"
            )
        self.confirmation_id = None
        self.confirmed_cart_version = None
        self.state = PurchaseState.CANCELLED

    def allowed_tools(self) -> set[str]:
        match self.state:
            case PurchaseState.UNDERSTANDING:
                return {"generate_ingredient_list", "recommend_dishes"}
            case PurchaseState.GATHERING_CONTEXT:
                return set(READ_CONTEXT_TOOLS)
            case PurchaseState.SEARCHING:
                return READ_CONTEXT_TOOLS | SEARCH_TOOLS
            case PurchaseState.BUILDING_CART:
                return READ_CONTEXT_TOOLS | SEARCH_TOOLS | ASSISTANT_CART_TOOLS
            case PurchaseState.AWAITING_CONFIRMATION | PurchaseState.AWAITING_RECONFIRMATION:
                return {"assistant_cart.get"}
            case PurchaseState.REVALIDATING:
                return {
                    "get_current_store",
                    "get_current_cart",
                    "check_price_and_stock",
                }
            case PurchaseState.SYNCING:
                return {"execute_cart_sync"}
            case PurchaseState.VERIFYING:
                return {"get_current_cart"}
            case _:
                return set()

    def _transition(
        self,
        target: PurchaseState,
        *,
        from_states: set[PurchaseState],
    ) -> None:
        if self.state not in from_states:
            raise InvalidPurchaseTransition(
                f"Cannot transition from {self.state} to {target}"
            )
        self.state = target
