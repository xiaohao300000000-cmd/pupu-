from __future__ import annotations

from dataclasses import dataclass, replace

from pupu_assistant.application.orchestrator import PurchaseAgent
from pupu_assistant.application.purchase_sessions import PurchaseSessionService
from pupu_assistant.application.purchase_tools import (
    ProductFactRecorder,
    PurchaseToolset,
)
from pupu_assistant.application.state_machine import PurchaseState
from pupu_assistant.domain.purchase.session import PurchaseSessionSnapshot
from pupu_assistant.integrations.llm.provider import LLMProvider
from pupu_assistant.integrations.pupu.connector import PupuConnector


class PurchasePlanningError(RuntimeError):
    pass


class PurchasePlanningStateInvalid(PurchasePlanningError):
    pass


class CurrentStoreUnavailable(PurchasePlanningError):
    pass


class ProductCandidatesUnavailable(PurchasePlanningError):
    pass


class AssistantCartPlanEmpty(PurchasePlanningError):
    pass


@dataclass(frozen=True)
class PurchasePlanningResult:
    message: str
    session: PurchaseSessionSnapshot


class PurchasePlanningWorkflow:
    """Runs the verified-store, product-search, and assistant-cart planning phases."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        connector: PupuConnector,
        sessions: PurchaseSessionService,
        max_tool_rounds: int,
        product_facts: ProductFactRecorder | None = None,
    ) -> None:
        self._provider = provider
        self._connector = connector
        self._sessions = sessions
        self._max_tool_rounds = max_tool_rounds
        self._product_facts = product_facts

    async def plan(
        self,
        *,
        task_id: str,
        user_id: str,
    ) -> PurchasePlanningResult:
        snapshot = self._sessions.load(task_id=task_id, user_id=user_id)
        if snapshot.state_machine.state is not PurchaseState.GATHERING_CONTEXT:
            raise PurchasePlanningStateInvalid(
                "Purchase task is not ready to gather platform context"
            )
        if snapshot.context.understanding is None:
            raise PurchasePlanningStateInvalid(
                "Purchase task has no structured understanding"
            )

        tools = PurchaseToolset(
            connector=self._connector,
            sessions=self._sessions,
            task_id=task_id,
            user_id=user_id,
            product_facts=self._product_facts,
        ).build_registry()
        agent = PurchaseAgent(
            provider=self._provider,
            tools=tools,
            max_tool_rounds=self._max_tool_rounds,
        )

        await agent.run(
            "Resolve the user's current store before searching for products.",
            allowed_tools=snapshot.state_machine.allowed_tools(),
        )
        snapshot = self._sessions.load(task_id=task_id, user_id=user_id)
        if snapshot.cart is None:
            raise CurrentStoreUnavailable(
                "Connector did not resolve a current store for the purchase task"
            )

        machine = replace(snapshot.state_machine)
        machine.begin_search()
        snapshot = snapshot.model_copy(update={"state_machine": machine})
        self._sessions.save_progress(snapshot)

        understanding_json = snapshot.context.understanding.model_dump_json()
        await agent.run(
            "Search verified Connector products for every requirement. "
            "Pass the matching requirement_id to each search call. "
            f"Structured requirements: {understanding_json}",
            allowed_tools=machine.allowed_tools(),
        )
        snapshot = self._sessions.load(task_id=task_id, user_id=user_id)
        required_ids = {
            requirement.requirement_id
            for requirement in snapshot.context.understanding.requirements
        }
        candidate_ids = {
            candidate.requirement_id
            for candidate in snapshot.context.product_candidates
        }
        if not required_ids or not required_ids.issubset(candidate_ids):
            raise ProductCandidatesUnavailable(
                "Verified product candidates are unavailable for all requirements"
            )

        machine = replace(snapshot.state_machine)
        machine.begin_cart_build()
        snapshot = snapshot.model_copy(update={"state_machine": machine})
        self._sessions.save_progress(snapshot)

        candidates = [
            candidate.model_dump(mode="json")
            for candidate in snapshot.context.product_candidates
        ]
        result = await agent.run(
            "Choose only from these Connector-verified candidates and add the best "
            "match for every requirement to the assistant cart. Do not write the "
            "platform cart. Include a concise selection_reason based only on the "
            "provided candidate facts and user constraints. "
            f"Candidates: {candidates}",
            allowed_tools=machine.allowed_tools(),
        )
        snapshot = self._sessions.load(task_id=task_id, user_id=user_id)
        if snapshot.cart is None or not snapshot.cart.items:
            raise AssistantCartPlanEmpty(
                "Agent did not create an assistant cart from verified products"
            )

        machine = replace(snapshot.state_machine)
        machine.request_confirmation()
        snapshot = snapshot.model_copy(update={"state_machine": machine})
        self._sessions.save_progress(snapshot)
        return PurchasePlanningResult(message=result.content, session=snapshot)
