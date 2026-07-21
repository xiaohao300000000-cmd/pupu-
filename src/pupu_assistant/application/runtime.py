from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from pupu_assistant.application.cart_revision import CartRevisionWorkflow
from pupu_assistant.application.planning import PurchasePlanningWorkflow
from pupu_assistant.application.purchase_sessions import PurchaseSessionService
from pupu_assistant.application.repurchase import RepurchaseWorkflow
from pupu_assistant.application.understanding import PurchaseUnderstandingWorkflow
from pupu_assistant.config import Settings
from pupu_assistant.entrypoints.feishu.events import (
    LarkCliCardActionEvent,
    LarkCliMessageEvent,
)
from pupu_assistant.entrypoints.feishu.handler import (
    FeishuHandlerResult,
    FeishuPurchaseHandler,
)
from pupu_assistant.integrations.llm.deepseek import (
    DeepSeekConfigurationError,
    DeepSeekProvider,
)
from pupu_assistant.integrations.pupu.connector import PupuConnector
from pupu_assistant.storage.event_dedup_repository import (
    SqlAlchemyEventDedupRepository,
)
from pupu_assistant.storage.household_memory_repository import (
    SqlAlchemyHouseholdMemoryRepository,
)
from pupu_assistant.storage.product_catalog_repository import (
    SqlAlchemyProductCatalogRepository,
)
from pupu_assistant.storage.purchase_session_repository import (
    SqlAlchemyPurchaseSessionRepository,
)


class AssistantRuntimeConfigurationError(RuntimeError):
    pass


@dataclass
class AssistantRuntime:
    """Composition root that returns responses but performs no Feishu sending."""

    settings: Settings
    connector: PupuConnector
    provider: DeepSeekProvider
    session_repository: SqlAlchemyPurchaseSessionRepository
    event_repository: SqlAlchemyEventDedupRepository
    household_repository: SqlAlchemyHouseholdMemoryRepository
    catalog_repository: SqlAlchemyProductCatalogRepository
    handler: FeishuPurchaseHandler

    async def handle_lark_cli_event(
        self,
        payload: Mapping[str, object],
    ) -> FeishuHandlerResult:
        event_type = payload.get("type")
        if event_type == "im.message.receive_v1":
            event = LarkCliMessageEvent.model_validate(payload)
            return await self.handler.handle_text(event.to_text_message())
        if event_type == "card.action.trigger":
            event = LarkCliCardActionEvent.model_validate(payload)
            return await self.handler.handle_card_action(event)
        raise ValueError(f"Unsupported Feishu event type: {event_type}")

    async def aclose(self) -> None:
        await self.provider.aclose()
        self.catalog_repository.close()
        self.household_repository.close()
        self.event_repository.close()
        self.session_repository.close()

    async def __aenter__(self) -> AssistantRuntime:
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback
        await self.aclose()


def build_assistant_runtime(
    *,
    settings: Settings,
    connector: PupuConnector,
) -> AssistantRuntime:
    """Wire the local application around an explicitly supplied Connector."""

    if settings.llm_provider.casefold() != "deepseek":
        raise AssistantRuntimeConfigurationError(
            f"Unsupported LLM provider: {settings.llm_provider}"
        )
    if settings.llm_api_key is None:
        raise DeepSeekConfigurationError("LLM_API_KEY is required")

    provider = DeepSeekProvider(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    session_repository = SqlAlchemyPurchaseSessionRepository(
        settings.pupu_database_path
    )
    event_repository = SqlAlchemyEventDedupRepository(settings.pupu_database_path)
    household_repository = SqlAlchemyHouseholdMemoryRepository(
        settings.pupu_database_path
    )
    catalog_repository = SqlAlchemyProductCatalogRepository(
        settings.pupu_database_path
    )
    sessions = PurchaseSessionService(session_repository)
    understanding = PurchaseUnderstandingWorkflow(
        provider=provider,
        sessions=sessions,
        max_tool_rounds=settings.llm_max_tool_rounds,
        household_context=household_repository,
    )
    planning = PurchasePlanningWorkflow(
        provider=provider,
        connector=connector,
        sessions=sessions,
        max_tool_rounds=settings.llm_max_tool_rounds,
        product_facts=catalog_repository,
    )
    cart_revision = CartRevisionWorkflow(
        provider=provider,
        sessions=sessions,
        max_tool_rounds=settings.llm_max_tool_rounds,
    )
    repurchase = RepurchaseWorkflow(
        connector=connector,
        sessions=sessions,
        product_facts=catalog_repository,
    )
    handler = FeishuPurchaseHandler(
        understanding=understanding,
        planning=planning,
        sessions=sessions,
        events=event_repository,
        cart_revision=cart_revision,
        repurchase=repurchase,
    )
    return AssistantRuntime(
        settings=settings,
        connector=connector,
        provider=provider,
        session_repository=session_repository,
        event_repository=event_repository,
        household_repository=household_repository,
        catalog_repository=catalog_repository,
        handler=handler,
    )
