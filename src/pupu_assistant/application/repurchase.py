from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Protocol

from pupu_assistant.application.purchase_sessions import PurchaseSessionService
from pupu_assistant.application.purchase_tools import ProductFactRecorder
from pupu_assistant.application.state_machine import PurchaseState
from pupu_assistant.domain.assistant_cart.models import ProductSnapshot
from pupu_assistant.domain.purchase.requirements import (
    ProductCandidate,
    PurchaseIntent,
    PurchaseRequirement,
    PurchaseUnderstanding,
)
from pupu_assistant.domain.purchase.session import PurchaseSessionSnapshot
from pupu_assistant.domain.repurchase import (
    RepurchaseLine,
    RepurchaseLineStatus,
    RepurchasePlan,
)
from pupu_assistant.integrations.pupu.connector import (
    OrderItem,
    ProductFilters,
    PupuConnector,
    PupuConnectorContractViolation,
    PupuConnectorError,
)


class RepurchasePlanningError(RuntimeError):
    pass


class RepurchaseStateInvalid(RepurchasePlanningError):
    pass


class PreviousOrderUnavailable(RepurchasePlanningError):
    pass


class RepurchaseProductsUnavailable(RepurchasePlanningError):
    pass


class ShoppingHistoryRecorder(Protocol):
    def cache_purchase(
        self,
        *,
        user_id: str,
        order_id: str,
        store_id: str,
        product_id: str,
        store_product_id: str,
        product_name: str,
        specification: str,
        quantity: int,
        purchased_unit_price: Decimal,
        purchased_at: datetime,
    ) -> object: ...


@dataclass(frozen=True)
class RepurchasePlanningResult:
    message: str
    session: PurchaseSessionSnapshot


class RepurchaseWorkflow:
    """Builds an assistant cart from real previous-order Connector facts."""

    def __init__(
        self,
        *,
        connector: PupuConnector,
        sessions: PurchaseSessionService,
        product_facts: ProductFactRecorder | None = None,
        shopping_history: ShoppingHistoryRecorder | None = None,
    ) -> None:
        self._connector = connector
        self._sessions = sessions
        self._product_facts = product_facts
        self._shopping_history = shopping_history

    async def plan_previous_day(
        self,
        *,
        task_id: str,
        user_id: str,
        now: datetime | None = None,
    ) -> RepurchasePlanningResult:
        snapshot = self._sessions.load(task_id=task_id, user_id=user_id)
        if snapshot.state_machine.state is not PurchaseState.GATHERING_CONTEXT:
            raise RepurchaseStateInvalid(
                "repurchase task is not ready to gather order context"
            )
        if (
            snapshot.context.understanding is None
            or snapshot.context.understanding.intent is not PurchaseIntent.REPURCHASE
        ):
            raise RepurchaseStateInvalid("purchase task is not a repurchase request")

        now = self._as_aware(now or datetime.now(UTC))
        previous_date = (now - timedelta(days=1)).date()
        start_time = datetime.combine(previous_date, time.min, tzinfo=now.tzinfo)
        end_time = start_time + timedelta(days=1)
        store = await self._connector.get_current_store(user_id=user_id)
        orders = await self._connector.get_orders(
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
        )
        order = next(
            (
                order
                for order in sorted(
                    orders,
                    key=lambda candidate: self._as_aware(candidate.created_at),
                    reverse=True,
                )
                if order.store_id == store.store_id
            ),
            None,
        )
        if order is None:
            raise PreviousOrderUnavailable(
                "No previous-day order is available for the current store"
            )
        detail = await self._connector.get_order_detail(
            user_id=user_id,
            order_id=order.order_id,
        )
        if (
            detail.order.order_id != order.order_id
            or detail.order.store_id != store.store_id
        ):
            raise PupuConnectorContractViolation(
                "Connector returned an order detail from another order or store"
            )

        snapshot = self._sessions.attach_cart(
            task_id=task_id,
            user_id=user_id,
            store_id=store.store_id,
        )
        machine = replace(snapshot.state_machine)
        machine.begin_search()
        machine.begin_cart_build()
        snapshot = snapshot.model_copy(update={"state_machine": machine})
        self._sessions.save_progress(snapshot)

        lines: list[RepurchaseLine] = []
        requirements: list[PurchaseRequirement] = []
        candidates: list[ProductCandidate] = []
        current_total = Decimal("0")
        for index, order_item in enumerate(detail.items, start=1):
            self._cache_purchase(
                user_id=user_id,
                order_id=order.order_id,
                store_id=store.store_id,
                purchased_at=order.created_at,
                item=order_item,
            )
            requirement_id = (
                f"repurchase:{order.order_id}:{index}:{order_item.store_product_id}"
            )
            requirements.append(self._requirement(requirement_id, order_item))
            line, line_candidates = await self._current_line(
                user_id=user_id,
                store_id=store.store_id,
                requirement_id=requirement_id,
                item=order_item,
            )
            lines.append(line)
            candidates.extend(line_candidates)
            if line.current_product is None:
                continue
            current_total += line.current_product.unit_price * line.quantity
            self._record_product(line.current_product)
            for substitute in line.substitutes:
                self._record_product(substitute)
            snapshot = self._sessions.add_product(
                task_id=task_id,
                user_id=user_id,
                product=line.current_product,
                quantity=line.quantity,
                operation_id=f"repurchase:{order.order_id}:{index}:add",
            )

        if snapshot.cart is None or not snapshot.cart.items:
            raise RepurchaseProductsUnavailable(
                "No current product facts were available for the previous order"
            )
        plan = RepurchasePlan(
            order_id=order.order_id,
            purchased_at=order.created_at,
            original_total=order.total_amount,
            current_estimated_total=current_total,
            lines=tuple(lines),
        )
        understanding = PurchaseUnderstanding(
            intent=PurchaseIntent.REPURCHASE,
            requirements=tuple(requirements),
        )
        context = snapshot.context.model_copy(
            update={
                "understanding": understanding,
                "product_candidates": tuple(candidates),
                "repurchase_plan": plan,
            }
        )
        machine = replace(snapshot.state_machine)
        machine.request_confirmation()
        snapshot = snapshot.model_copy(
            update={"context": context, "state_machine": machine}
        )
        self._sessions.save_progress(snapshot)
        return RepurchasePlanningResult(
            message=self._summary(plan),
            session=snapshot,
        )

    async def _current_line(
        self,
        *,
        user_id: str,
        store_id: str,
        requirement_id: str,
        item: OrderItem,
    ) -> tuple[RepurchaseLine, tuple[ProductCandidate, ...]]:
        try:
            current = await self._connector.get_product_detail(
                user_id=user_id,
                store_id=store_id,
                store_product_id=item.store_product_id,
            )
        except PupuConnectorError as error:
            return (
                RepurchaseLine(
                    requirement_id=requirement_id,
                    product_id=item.product_id,
                    store_product_id=item.store_product_id,
                    product_name=item.name,
                    specification=item.specification,
                    quantity=item.quantity,
                    purchased_unit_price=item.purchased_unit_price,
                    status=RepurchaseLineStatus.UNAVAILABLE,
                    reason=f"当前商品查询失败：{type(error).__name__}",
                ),
                (),
            )
        self._verify_product(
            current,
            store_id=store_id,
            store_product_id=item.store_product_id,
        )
        substitutes = ()
        if not current.stock_available:
            try:
                substitutes = tuple(
                    substitute
                    for substitute in await self._connector.find_platform_substitutes(
                        user_id=user_id,
                        store_id=store_id,
                        product=current,
                        filters=ProductFilters(in_stock_only=True),
                        limit=3,
                    )
                    if substitute.store_id == store_id
                    and substitute.stock_available
                    and substitute.store_product_id
                )[:3]
            except PupuConnectorError:
                substitutes = ()
        price_delta = current.unit_price - item.purchased_unit_price
        if not current.stock_available:
            status = RepurchaseLineStatus.OUT_OF_STOCK
            reason = "原商品缺货，已保存的替代候选需要用户确认"
        elif price_delta != 0:
            status = RepurchaseLineStatus.PRICE_CHANGED
            reason = "当前单价与上次购买价格不同"
        else:
            status = RepurchaseLineStatus.UNCHANGED
            reason = "商品有货且单价与上次购买一致"
        products = (current, *substitutes)
        return (
            RepurchaseLine(
                requirement_id=requirement_id,
                product_id=item.product_id,
                store_product_id=item.store_product_id,
                product_name=item.name,
                specification=item.specification,
                quantity=item.quantity,
                purchased_unit_price=item.purchased_unit_price,
                current_product=current,
                status=status,
                price_delta=price_delta,
                substitutes=substitutes,
                reason=reason,
            ),
            tuple(
                ProductCandidate(requirement_id=requirement_id, product=product)
                for product in products
            ),
        )

    @staticmethod
    def _requirement(
        requirement_id: str,
        item: OrderItem,
    ) -> PurchaseRequirement:
        return PurchaseRequirement(
            requirement_id=requirement_id,
            normalized_name=item.name,
            category="历史复购",
            keywords=(item.name,),
            quantity=item.quantity,
            target_specification=item.specification,
        )

    @staticmethod
    def _verify_product(
        product: ProductSnapshot,
        *,
        store_id: str,
        store_product_id: str,
    ) -> None:
        if product.store_id != store_id:
            raise PupuConnectorContractViolation(
                "Connector returned a product from another store"
            )
        if product.store_product_id != store_product_id:
            raise PupuConnectorContractViolation(
                "Connector returned a different store product"
            )

    def _record_product(self, product: ProductSnapshot) -> None:
        if self._product_facts is not None:
            self._product_facts.record_product(product)

    def _cache_purchase(
        self,
        *,
        user_id: str,
        order_id: str,
        store_id: str,
        purchased_at: datetime,
        item: OrderItem,
    ) -> None:
        if self._shopping_history is None:
            return
        self._shopping_history.cache_purchase(
            user_id=user_id,
            order_id=order_id,
            store_id=store_id,
            product_id=item.product_id,
            store_product_id=item.store_product_id,
            product_name=item.name,
            specification=item.specification,
            quantity=item.quantity,
            purchased_unit_price=item.purchased_unit_price,
            purchased_at=purchased_at,
        )

    @staticmethod
    def _as_aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @staticmethod
    def _summary(plan: RepurchasePlan) -> str:
        return (
            f"已读取昨日订单，共 {len(plan.lines)} 件；"
            f"变化 {plan.changed_count} 件，缺货或不可用 "
            f"{plan.unavailable_count} 件。当前可核对商品预计 "
            f"¥{plan.current_estimated_total:.2f}。"
        )
