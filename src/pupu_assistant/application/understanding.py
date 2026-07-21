from __future__ import annotations

import json
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Protocol

from pydantic import ConfigDict, JsonValue

from pupu_assistant.application.orchestrator import (
    AgentResult,
    PurchaseAgent,
    PurchaseAgentError,
)
from pupu_assistant.application.purchase_sessions import PurchaseSessionService
from pupu_assistant.application.state_machine import PurchaseState
from pupu_assistant.application.tool_registry import ToolRegistry, ToolRisk, ToolSpec
from pupu_assistant.domain.household import (
    HouseholdContextSnapshot,
    HouseholdInventoryItem,
    PreferenceType,
    UserPreference,
)
from pupu_assistant.domain.purchase.requirements import (
    ClarificationExchange,
    PurchaseIntent,
    PurchaseUnderstanding,
)
from pupu_assistant.domain.purchase.session import (
    PurchaseSessionContext,
    PurchaseSessionSnapshot,
)
from pupu_assistant.integrations.llm.provider import LLMProvider


UNDERSTANDING_TOOL = "submit_purchase_understanding"

UNDERSTANDING_SYSTEM_PROMPT = """You are the understanding stage of a household
grocery purchase assistant. Convert the user's request into platform-independent
requirements. Never invent a product ID, price, stock value, store, order, or cart
result. When essential information is missing, submit exactly one concise
clarification question. Always call submit_purchase_understanding before answering.
Treat household preferences and inventory as user-maintained context, not platform
price or stock facts. For a recipe purchase, generate structured ingredient
requirements after accounting for stated household inventory, or ask one question
when servings or another essential constraint is missing. Do not call a platform API
or request credentials. For an explicit preference or inventory update, submit only
the corresponding structured changes; never modify memory during another intent."""


class SubmitPurchaseUnderstandingArguments(PurchaseUnderstanding):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UnderstandingNotSubmitted(RuntimeError):
    pass


class ClarificationNotExpected(RuntimeError):
    pass


class HouseholdMemoryProvider(Protocol):
    def snapshot(self, *, user_id: str) -> HouseholdContextSnapshot: ...

    def set_preference(
        self,
        *,
        user_id: str,
        preference_type: PreferenceType,
        target: str,
        value: JsonValue,
        confidence: Decimal,
        source: str,
    ) -> UserPreference: ...

    def delete_preference(
        self,
        *,
        user_id: str,
        preference_type: PreferenceType,
        target: str,
    ) -> bool: ...

    def upsert_inventory_item(
        self,
        *,
        user_id: str,
        ingredient_name: str,
        quantity: Decimal,
        unit: str,
        confidence: Decimal,
        source: str,
    ) -> HouseholdInventoryItem: ...

    def delete_inventory_item(
        self,
        *,
        user_id: str,
        ingredient_name: str,
    ) -> bool: ...


class HouseholdMemoryUnavailable(PurchaseAgentError):
    pass


@dataclass(frozen=True)
class UnderstandingResult:
    message: str
    tool_rounds: int
    session: PurchaseSessionSnapshot


class _UnderstandingCapture:
    def __init__(self) -> None:
        self.value: PurchaseUnderstanding | None = None

    def submit(self, arguments: SubmitPurchaseUnderstandingArguments) -> dict[str, bool]:
        self.value = PurchaseUnderstanding.model_validate(arguments.model_dump())
        return {"accepted": True}


class PurchaseUnderstandingWorkflow:
    """Creates and resumes the document-defined understanding/clarification stage."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        sessions: PurchaseSessionService,
        max_tool_rounds: int,
        household_context: HouseholdMemoryProvider | None = None,
    ) -> None:
        self._provider = provider
        self._sessions = sessions
        self._max_tool_rounds = max_tool_rounds
        self._household_context = household_context

    async def start(
        self,
        *,
        task_id: str,
        user_id: str,
        user_message: str,
    ) -> UnderstandingResult:
        snapshot = self._sessions.create(
            task_id=task_id,
            user_id=user_id,
            original_request=user_message,
        )
        machine = replace(snapshot.state_machine)
        machine.start_understanding()
        snapshot = snapshot.model_copy(update={"state_machine": machine})
        self._sessions.save_progress(snapshot)
        return await self._understand(snapshot, user_message)

    async def answer_clarification(
        self,
        *,
        task_id: str,
        user_id: str,
        answer: str,
    ) -> UnderstandingResult:
        snapshot = self._sessions.load(task_id=task_id, user_id=user_id)
        question = snapshot.context.pending_question
        if (
            snapshot.state_machine.state is not PurchaseState.AWAITING_CLARIFICATION
            or question is None
        ):
            raise ClarificationNotExpected(
                "Purchase task is not waiting for a clarification answer"
            )
        exchange = ClarificationExchange(question=question, answer=answer)
        context = snapshot.context.model_copy(
            update={
                "pending_question": None,
                "clarification_history": (
                    *snapshot.context.clarification_history,
                    exchange,
                ),
            }
        )
        machine = replace(snapshot.state_machine)
        machine.resume_understanding()
        snapshot = snapshot.model_copy(
            update={"context": context, "state_machine": machine}
        )
        self._sessions.save_progress(snapshot)
        prompt = (
            f"Original request: {context.original_request}\n"
            f"Clarification question: {question}\n"
            f"User answer: {answer}"
        )
        return await self._understand(snapshot, prompt)

    async def _understand(
        self,
        snapshot: PurchaseSessionSnapshot,
        prompt: str,
    ) -> UnderstandingResult:
        if self._household_context is not None:
            household_context = self._household_context.snapshot(
                user_id=snapshot.user_id
            )
            prompt = (
                f"{prompt}\nHousehold context: "
                f"{json.dumps(household_context.to_agent_context(), ensure_ascii=False)}"
            )
        capture = _UnderstandingCapture()
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name=UNDERSTANDING_TOOL,
                description=(
                    "Submit structured purchase requirements or one clarification question"
                ),
                arguments_model=SubmitPurchaseUnderstandingArguments,
                handler=capture.submit,
                risk=ToolRisk.READ_ONLY,
            )
        )
        agent = PurchaseAgent(
            provider=self._provider,
            tools=registry,
            max_tool_rounds=self._max_tool_rounds,
            system_prompt=UNDERSTANDING_SYSTEM_PROMPT,
        )
        agent_result = await agent.run(prompt, allowed_tools={UNDERSTANDING_TOOL})
        if capture.value is None:
            raise UnderstandingNotSubmitted(
                "DeepSeek did not submit structured purchase requirements"
            )
        updated = self._apply_understanding(snapshot, capture.value)
        self._sessions.save_progress(updated)
        return self._result(agent_result, updated)

    def _apply_understanding(
        self,
        snapshot: PurchaseSessionSnapshot,
        understanding: PurchaseUnderstanding,
    ) -> PurchaseSessionSnapshot:
        context = PurchaseSessionContext(
            original_request=snapshot.context.original_request,
            pending_question=understanding.clarification_question,
            dish_name=understanding.dish_name,
            servings=understanding.servings,
            budget=understanding.budget,
            last_card_action_id=snapshot.context.last_card_action_id,
            understanding=understanding,
            clarification_history=snapshot.context.clarification_history,
            product_candidates=snapshot.context.product_candidates,
            previous_cart=snapshot.context.previous_cart,
        )
        machine = replace(snapshot.state_machine)
        if understanding.clarification_question:
            machine.await_clarification()
        elif understanding.intent is PurchaseIntent.PREFERENCE_UPDATE:
            household_memory = self._require_household_memory()
            for change in understanding.preference_changes:
                if change.delete:
                    household_memory.delete_preference(
                        user_id=snapshot.user_id,
                        preference_type=change.preference_type,
                        target=change.target,
                    )
                else:
                    assert change.value is not None
                    household_memory.set_preference(
                        user_id=snapshot.user_id,
                        preference_type=change.preference_type,
                        target=change.target,
                        value=change.value,
                        confidence=change.confidence,
                        source="user",
                    )
            machine.complete_local_update()
        elif understanding.intent is PurchaseIntent.INVENTORY_UPDATE:
            household_memory = self._require_household_memory()
            for change in understanding.inventory_changes:
                if change.delete:
                    household_memory.delete_inventory_item(
                        user_id=snapshot.user_id,
                        ingredient_name=change.ingredient_name,
                    )
                else:
                    assert change.quantity is not None
                    assert change.unit is not None
                    household_memory.upsert_inventory_item(
                        user_id=snapshot.user_id,
                        ingredient_name=change.ingredient_name,
                        quantity=change.quantity,
                        unit=change.unit,
                        confidence=change.confidence,
                        source="user",
                    )
            machine.complete_local_update()
        else:
            machine.gather_context()
        return snapshot.model_copy(
            update={"context": context, "state_machine": machine}
        )

    def _require_household_memory(self) -> HouseholdMemoryProvider:
        if self._household_context is None:
            raise HouseholdMemoryUnavailable(
                "Household memory is not configured for this runtime"
            )
        return self._household_context

    @staticmethod
    def _result(
        agent_result: AgentResult,
        snapshot: PurchaseSessionSnapshot,
    ) -> UnderstandingResult:
        return UnderstandingResult(
            message=agent_result.content,
            tool_rounds=agent_result.tool_rounds,
            session=snapshot,
        )
