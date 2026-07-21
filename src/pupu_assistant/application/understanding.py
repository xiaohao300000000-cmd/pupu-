from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Protocol

from pydantic import ConfigDict

from pupu_assistant.application.orchestrator import AgentResult, PurchaseAgent
from pupu_assistant.application.purchase_sessions import PurchaseSessionService
from pupu_assistant.application.state_machine import PurchaseState
from pupu_assistant.application.tool_registry import ToolRegistry, ToolRisk, ToolSpec
from pupu_assistant.domain.household import HouseholdContextSnapshot
from pupu_assistant.domain.purchase.requirements import (
    ClarificationExchange,
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
or request credentials."""


class SubmitPurchaseUnderstandingArguments(PurchaseUnderstanding):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UnderstandingNotSubmitted(RuntimeError):
    pass


class ClarificationNotExpected(RuntimeError):
    pass


class HouseholdContextProvider(Protocol):
    def snapshot(self, *, user_id: str) -> HouseholdContextSnapshot: ...


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
        household_context: HouseholdContextProvider | None = None,
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

    @staticmethod
    def _apply_understanding(
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
        )
        machine = replace(snapshot.state_machine)
        if understanding.clarification_question:
            machine.await_clarification()
        else:
            machine.gather_context()
        return snapshot.model_copy(
            update={"context": context, "state_machine": machine}
        )

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
