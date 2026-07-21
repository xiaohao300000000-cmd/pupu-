from __future__ import annotations

import json
from dataclasses import dataclass, replace

from pydantic import BaseModel, ConfigDict, Field

from pupu_assistant.application.orchestrator import PurchaseAgent
from pupu_assistant.application.purchase_sessions import (
    AssistantCartUndoUnavailable,
    PurchaseSessionService,
)
from pupu_assistant.application.state_machine import PurchaseState
from pupu_assistant.application.tool_registry import ToolRegistry, ToolRisk, ToolSpec
from pupu_assistant.domain.purchase.session import PurchaseSessionSnapshot
from pupu_assistant.integrations.llm.provider import LLMProvider


CART_REVISION_STATES = {
    PurchaseState.AWAITING_CONFIRMATION,
    PurchaseState.AWAITING_RECONFIRMATION,
}

CART_REVISION_SYSTEM_PROMPT = """You revise an existing household assistant cart.
Use only the provided assistant-cart tools and product identifiers. Never invent a
product, price, stock value, platform identifier, or alternative. A replacement is
valid only when the tool accepts an already-saved candidate. Apply the user's request
incrementally; do not rebuild unrelated cart items. If the request only asks to view
the cart, read it without changing it. If the user asks to sync, order, or pay, do not
perform that action and explain that the separate confirmation flow is required. Use
assistant_cart.undo only for an explicit request to undo the last unsynced change. Use
assistant_cart.cancel only for an explicit request to cancel the current task."""


class EmptyCartRevisionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetCartQuantityArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)


class RemoveCartProductArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)


class ReplaceCartProductArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    replacement_product_id: str = Field(min_length=1)


class CartRevisionError(RuntimeError):
    pass


class CartRevisionUnavailable(CartRevisionError):
    pass


class CartRevisionCandidateRejected(CartRevisionError):
    pass


@dataclass(frozen=True)
class CartRevisionResult:
    message: str
    session: PurchaseSessionSnapshot
    changed: bool


class _CartRevisionTools:
    def __init__(
        self,
        *,
        sessions: PurchaseSessionService,
        snapshot: PurchaseSessionSnapshot,
        request_id: str,
    ) -> None:
        self._sessions = sessions
        self._task_id = snapshot.task_id
        self._user_id = snapshot.user_id
        self._request_id = request_id
        self._operation_index = 0
        self.last_action: str | None = None

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="assistant_cart.get",
                description="Read the current independent assistant cart",
                arguments_model=EmptyCartRevisionArguments,
                handler=self._get_cart,
                risk=ToolRisk.ASSISTANT_CART,
            )
        )
        registry.register(
            ToolSpec(
                name="assistant_cart.set_quantity",
                description="Set the quantity of an existing assistant-cart product",
                arguments_model=SetCartQuantityArguments,
                handler=self._set_quantity,
                risk=ToolRisk.ASSISTANT_CART,
            )
        )
        registry.register(
            ToolSpec(
                name="assistant_cart.remove",
                description="Remove an existing product from the assistant cart",
                arguments_model=RemoveCartProductArguments,
                handler=self._remove,
                risk=ToolRisk.ASSISTANT_CART,
            )
        )
        registry.register(
            ToolSpec(
                name="assistant_cart.replace",
                description=(
                    "Replace a cart product with an already-saved candidate from the "
                    "same requirement and store"
                ),
                arguments_model=ReplaceCartProductArguments,
                handler=self._replace,
                risk=ToolRisk.ASSISTANT_CART,
            )
        )
        registry.register(
            ToolSpec(
                name="assistant_cart.undo",
                description="Undo the most recent unsynced assistant-cart change",
                arguments_model=EmptyCartRevisionArguments,
                handler=self._undo,
                risk=ToolRisk.ASSISTANT_CART,
            )
        )
        registry.register(
            ToolSpec(
                name="assistant_cart.cancel",
                description="Cancel the current local purchase task",
                arguments_model=EmptyCartRevisionArguments,
                handler=self._cancel,
                risk=ToolRisk.ASSISTANT_CART,
            )
        )
        return registry

    def _get_cart(self, arguments: EmptyCartRevisionArguments):
        del arguments
        return self._load().cart

    def _set_quantity(self, arguments: SetCartQuantityArguments):
        self._require_current_product(arguments.product_id)
        return self._sessions.set_quantity(
            task_id=self._task_id,
            user_id=self._user_id,
            product_id=arguments.product_id,
            quantity=arguments.quantity,
            operation_id=self._operation_id("set_quantity"),
        ).cart

    def _remove(self, arguments: RemoveCartProductArguments):
        self._require_current_product(arguments.product_id)
        return self._sessions.remove_product(
            task_id=self._task_id,
            user_id=self._user_id,
            product_id=arguments.product_id,
            operation_id=self._operation_id("remove"),
        ).cart

    def _replace(self, arguments: ReplaceCartProductArguments):
        snapshot = self._load()
        if snapshot.cart is None:
            raise CartRevisionUnavailable("assistant cart is unavailable")
        self._require_current_product(arguments.product_id)
        requirement_ids = {
            candidate.requirement_id
            for candidate in snapshot.context.product_candidates
            if candidate.product.product_id == arguments.product_id
        }
        replacement = next(
            (
                candidate.product
                for candidate in snapshot.context.product_candidates
                if candidate.requirement_id in requirement_ids
                and candidate.product.product_id == arguments.replacement_product_id
                and candidate.product.store_id == snapshot.cart.store_id
                and candidate.product.stock_available
            ),
            None,
        )
        if replacement is None:
            raise CartRevisionCandidateRejected(
                "replacement must be an in-stock saved candidate for the same requirement"
            )
        return self._sessions.replace_product(
            task_id=self._task_id,
            user_id=self._user_id,
            product_id=arguments.product_id,
            replacement=replacement,
            operation_id=self._operation_id("replace"),
        ).cart

    def _undo(self, arguments: EmptyCartRevisionArguments):
        del arguments
        try:
            return self._sessions.undo_last_cart_change(
                task_id=self._task_id,
                user_id=self._user_id,
                operation_id=self._operation_id("undo"),
            ).cart
        except AssistantCartUndoUnavailable as error:
            raise CartRevisionUnavailable(str(error)) from error

    def _cancel(self, arguments: EmptyCartRevisionArguments):
        del arguments
        return self._sessions.cancel(
            task_id=self._task_id,
            user_id=self._user_id,
            action_id=self._operation_id("cancel"),
        ).state_machine.state.value

    def _load(self) -> PurchaseSessionSnapshot:
        return self._sessions.load(task_id=self._task_id, user_id=self._user_id)

    def _require_current_product(self, product_id: str) -> None:
        snapshot = self._load()
        if snapshot.cart is None or not any(
            item.product.product_id == product_id for item in snapshot.cart.items
        ):
            raise CartRevisionCandidateRejected(
                "product is not in the current assistant cart"
            )

    def _operation_id(self, action: str) -> str:
        self._operation_index += 1
        self.last_action = action
        return f"{self._request_id}:{self._operation_index}:{action}"


class CartRevisionWorkflow:
    """Lets DeepSeek incrementally revise only a persisted assistant cart."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        sessions: PurchaseSessionService,
        max_tool_rounds: int,
    ) -> None:
        self._provider = provider
        self._sessions = sessions
        self._max_tool_rounds = max_tool_rounds

    async def revise(
        self,
        *,
        task_id: str,
        user_id: str,
        user_message: str,
        request_id: str,
    ) -> CartRevisionResult:
        snapshot = self._sessions.load(task_id=task_id, user_id=user_id)
        if snapshot.state_machine.state not in CART_REVISION_STATES:
            raise CartRevisionUnavailable(
                "purchase task is not waiting for assistant-cart confirmation"
            )
        if snapshot.cart is None:
            raise CartRevisionUnavailable("purchase task has no assistant cart")
        original_version = snapshot.cart.version
        original_cart = snapshot.cart
        revision_tools = _CartRevisionTools(
            sessions=self._sessions,
            snapshot=snapshot,
            request_id=request_id,
        )
        tools = revision_tools.build_registry()
        agent = PurchaseAgent(
            provider=self._provider,
            tools=tools,
            max_tool_rounds=self._max_tool_rounds,
            system_prompt=CART_REVISION_SYSTEM_PROMPT,
        )
        context = {
            "cart": snapshot.cart.model_dump(mode="json"),
            "saved_candidates": [
                candidate.model_dump(mode="json")
                for candidate in snapshot.context.product_candidates
            ],
        }
        result = await agent.run(
            "User request: "
            f"{user_message}\nCurrent task context: "
            f"{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}",
            allowed_tools={
                "assistant_cart.get",
                "assistant_cart.set_quantity",
                "assistant_cart.remove",
                "assistant_cart.replace",
                "assistant_cart.undo",
                "assistant_cart.cancel",
            },
        )
        updated = self._sessions.load(task_id=task_id, user_id=user_id)
        changed = updated.cart is not None and updated.cart.version != original_version
        if changed and updated.state_machine.state is not PurchaseState.CANCELLED:
            machine = replace(updated.state_machine)
            if updated.cart is not None and updated.cart.items:
                machine.request_confirmation()
            else:
                machine.cancel()
            context_snapshot = updated.context.model_copy(
                update={
                    "last_card_action_id": request_id,
                    "previous_cart": (
                        None
                        if revision_tools.last_action == "undo"
                        else original_cart
                    ),
                }
            )
            updated = updated.model_copy(
                update={"state_machine": machine, "context": context_snapshot}
            )
            self._sessions.save_progress(updated)
        return CartRevisionResult(
            message=result.content,
            session=updated,
            changed=changed,
        )
