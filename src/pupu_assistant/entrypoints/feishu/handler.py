from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from pupu_assistant.application.orchestrator import PurchaseAgentError
from pupu_assistant.application.planning import (
    PurchasePlanningError,
    PurchasePlanningWorkflow,
)
from pupu_assistant.application.purchase_sessions import PurchaseSessionService
from pupu_assistant.application.state_machine import (
    InvalidPurchaseTransition,
    PurchaseState,
)
from pupu_assistant.application.understanding import (
    PurchaseUnderstandingWorkflow,
    UnderstandingResult,
)
from pydantic import ValidationError

from pupu_assistant.entrypoints.feishu.cards import (
    CartCardAction,
    CartCardActionValue,
)
from pupu_assistant.entrypoints.feishu.events import (
    FeishuTextMessage,
    LarkCliCardActionEvent,
)
from pupu_assistant.domain.purchase.session import PurchaseSessionSnapshot
from pupu_assistant.integrations.llm.deepseek import DeepSeekError
from pupu_assistant.integrations.pupu.connector import PupuConnectorError


class EventDedupRepository(Protocol):
    def claim(
        self, *, event_id: str, event_type: str, user_id: str
    ) -> bool: ...


@dataclass(frozen=True)
class FeishuHandlerResult:
    event_id: str
    task_id: str | None
    reply_text: str | None
    duplicate: bool


class FeishuPurchaseHandler:
    """Maps Feishu text events to one recoverable task per user."""

    def __init__(
        self,
        *,
        understanding: PurchaseUnderstandingWorkflow,
        planning: PurchasePlanningWorkflow,
        sessions: PurchaseSessionService,
        events: EventDedupRepository,
    ) -> None:
        self._understanding = understanding
        self._planning = planning
        self._sessions = sessions
        self._events = events

    async def handle_text(self, message: FeishuTextMessage) -> FeishuHandlerResult:
        claimed = self._events.claim(
            event_id=message.event_id,
            event_type="im.message.receive_v1",
            user_id=message.sender_open_id,
        )
        if not claimed:
            return FeishuHandlerResult(
                event_id=message.event_id,
                task_id=None,
                reply_text=None,
                duplicate=True,
            )

        active = self._sessions.load_latest_active(user_id=message.sender_open_id)
        try:
            if active is None:
                result = await self._understanding.start(
                    task_id=f"feishu:{message.message_id}",
                    user_id=message.sender_open_id,
                    user_message=message.text,
                )
                return await self._continue(result, event_id=message.event_id)
            if active.state_machine.state is PurchaseState.AWAITING_CLARIFICATION:
                result = await self._understanding.answer_clarification(
                    task_id=active.task_id,
                    user_id=active.user_id,
                    answer=message.text,
                )
                return await self._continue(result, event_id=message.event_id)
            return FeishuHandlerResult(
                event_id=message.event_id,
                task_id=active.task_id,
                reply_text=self._active_task_reply(active.state_machine.state),
                duplicate=False,
            )
        except (PurchaseAgentError, DeepSeekError) as error:
            return FeishuHandlerResult(
                event_id=message.event_id,
                task_id=active.task_id if active else f"feishu:{message.message_id}",
                reply_text=(
                    "需求已保存，但采购理解服务暂时不可用。稍后可以继续，"
                    f"不需要重新描述。错误类型：{type(error).__name__}"
                ),
                duplicate=False,
            )

    async def handle_card_action(
        self,
        event: LarkCliCardActionEvent,
    ) -> FeishuHandlerResult:
        claimed = self._events.claim(
            event_id=event.event_id,
            event_type="card.action.trigger",
            user_id=event.operator_id,
        )
        if not claimed:
            return FeishuHandlerResult(
                event_id=event.event_id,
                task_id=None,
                reply_text=None,
                duplicate=True,
            )
        try:
            action = CartCardActionValue.model_validate(
                event.decoded_action_value()
            )
        except ValidationError:
            return FeishuHandlerResult(
                event_id=event.event_id,
                task_id=None,
                reply_text="无法识别这次卡片操作，请刷新采购方案后重试。",
                duplicate=False,
            )

        snapshot = self._sessions.load(
            task_id=action.task_id,
            user_id=event.operator_id,
        )
        if snapshot.cart is None or snapshot.cart.version != action.cart_version:
            return FeishuHandlerResult(
                event_id=event.event_id,
                task_id=action.task_id,
                reply_text="这张卡片已经过期，请使用最新采购方案。",
                duplicate=False,
            )

        if action.action is CartCardAction.SET_QUANTITY:
            assert action.product_id is not None
            assert action.quantity is not None
            snapshot = self._sessions.set_quantity(
                task_id=action.task_id,
                user_id=event.operator_id,
                product_id=action.product_id,
                quantity=action.quantity,
                operation_id=event.event_id,
            )
            snapshot = self._return_to_confirmation(snapshot)
            return self._card_result(event.event_id, snapshot, "数量已更新。")
        if action.action is CartCardAction.REMOVE:
            assert action.product_id is not None
            snapshot = self._sessions.remove_product(
                task_id=action.task_id,
                user_id=event.operator_id,
                product_id=action.product_id,
                operation_id=event.event_id,
            )
            if snapshot.cart is not None and not snapshot.cart.items:
                return self._card_result(
                    event.event_id,
                    snapshot,
                    "商品已删除，助手购物车现在为空；请重新描述要购买的商品。",
                )
            snapshot = self._return_to_confirmation(snapshot)
            return self._card_result(event.event_id, snapshot, "商品已删除。")
        if action.action is CartCardAction.CANCEL:
            machine = replace(snapshot.state_machine)
            machine.cancel()
            snapshot = snapshot.model_copy(update={"state_machine": machine})
            self._sessions.save_progress(snapshot)
            return self._card_result(event.event_id, snapshot, "当前采购任务已取消。")
        if action.action is CartCardAction.CONFIRM:
            return FeishuHandlerResult(
                event_id=event.event_id,
                task_id=snapshot.task_id,
                reply_text="采购方案已确认，但真实朴朴同步尚不可用；方案会继续保留。",
                duplicate=False,
            )
        raise InvalidPurchaseTransition(f"Unsupported cart action: {action.action}")

    async def _continue(
        self,
        result: UnderstandingResult,
        *,
        event_id: str,
    ) -> FeishuHandlerResult:
        snapshot = result.session
        if snapshot.state_machine.state is PurchaseState.AWAITING_CLARIFICATION:
            return FeishuHandlerResult(
                event_id=event_id,
                task_id=snapshot.task_id,
                reply_text=snapshot.context.pending_question or result.message,
                duplicate=False,
            )
        try:
            planned = await self._planning.plan(
                task_id=snapshot.task_id,
                user_id=snapshot.user_id,
            )
        except (PurchasePlanningError, PupuConnectorError) as error:
            return FeishuHandlerResult(
                event_id=event_id,
                task_id=snapshot.task_id,
                reply_text=(
                    "采购需求已经保存，但真实朴朴商品服务暂时不可用。"
                    "稍后可以从当前任务继续，不会生成虚假商品。"
                    f"错误类型：{type(error).__name__}"
                ),
                duplicate=False,
            )
        return FeishuHandlerResult(
            event_id=event_id,
            task_id=snapshot.task_id,
            reply_text=planned.message,
            duplicate=False,
        )

    @staticmethod
    def _active_task_reply(state: PurchaseState) -> str:
        if state is PurchaseState.AWAITING_CONFIRMATION:
            return "当前采购方案正在等待确认，请使用方案卡片进行修改或确认。"
        if state is PurchaseState.AUTH_REQUIRED:
            return "当前任务需要重新授权朴朴账号，采购方案已保留。"
        return f"当前采购任务仍在处理中，状态：{state.value}。"

    def _return_to_confirmation(
        self,
        snapshot: PurchaseSessionSnapshot,
    ) -> PurchaseSessionSnapshot:
        machine = replace(snapshot.state_machine)
        machine.request_confirmation()
        updated = snapshot.model_copy(update={"state_machine": machine})
        self._sessions.save_progress(updated)
        return updated

    @staticmethod
    def _card_result(
        event_id: str,
        snapshot: PurchaseSessionSnapshot,
        reply_text: str,
    ) -> FeishuHandlerResult:
        return FeishuHandlerResult(
            event_id=event_id,
            task_id=snapshot.task_id,
            reply_text=reply_text,
            duplicate=False,
        )
