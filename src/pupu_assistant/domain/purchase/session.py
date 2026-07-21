from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pupu_assistant.application.state_machine import PurchaseStateMachine
from pupu_assistant.domain.assistant_cart.service import AssistantCart
from pupu_assistant.domain.purchase.requirements import (
    ClarificationExchange,
    ProductCandidate,
    PurchaseUnderstanding,
)


class PurchaseSessionContext(BaseModel):
    """Short-lived task context needed to resume an interrupted conversation."""

    model_config = ConfigDict(frozen=True)

    original_request: str = Field(min_length=1)
    pending_question: str | None = None
    dish_name: str | None = None
    servings: int | None = Field(default=None, ge=1)
    budget: Decimal | None = Field(default=None, ge=0)
    last_card_action_id: str | None = None
    understanding: PurchaseUnderstanding | None = None
    clarification_history: tuple[ClarificationExchange, ...] = ()
    product_candidates: tuple[ProductCandidate, ...] = ()
    previous_cart: AssistantCart | None = None


class PurchaseSessionSnapshot(BaseModel):
    """One user's recoverable purchase task and independent assistant cart."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    task_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    context: PurchaseSessionContext
    state_machine: PurchaseStateMachine
    cart: AssistantCart | None = None

    @model_validator(mode="after")
    def require_matching_cart_version(self) -> PurchaseSessionSnapshot:
        if self.cart is None and self.state_machine.cart_version != 0:
            raise ValueError("a session without a cart must have cart version zero")
        if self.cart is not None and self.state_machine.cart_version != self.cart.version:
            raise ValueError("state machine cart version must match cart version")
        return self
