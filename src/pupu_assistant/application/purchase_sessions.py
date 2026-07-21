from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pupu_assistant.application.state_machine import PurchaseStateMachine
from pupu_assistant.domain.assistant_cart.models import ProductSnapshot
from pupu_assistant.domain.assistant_cart.service import AssistantCart
from pupu_assistant.domain.purchase.session import (
    PurchaseSessionContext,
    PurchaseSessionSnapshot,
)


class PurchaseSessionRepository(Protocol):
    def create(self, snapshot: PurchaseSessionSnapshot) -> None: ...

    def save(self, snapshot: PurchaseSessionSnapshot) -> None: ...

    def load(self, *, task_id: str, user_id: str) -> PurchaseSessionSnapshot: ...


class AssistantCartUnavailable(RuntimeError):
    pass


class AssistantCartStoreConflict(RuntimeError):
    pass


class PurchaseSessionService:
    """Coordinates recoverable task progress without touching the platform cart."""

    def __init__(self, repository: PurchaseSessionRepository) -> None:
        self._repository = repository

    def create(
        self,
        *,
        task_id: str,
        user_id: str,
        original_request: str,
    ) -> PurchaseSessionSnapshot:
        snapshot = PurchaseSessionSnapshot(
            task_id=task_id,
            user_id=user_id,
            context=PurchaseSessionContext(original_request=original_request),
            state_machine=PurchaseStateMachine(),
            cart=None,
        )
        self._repository.create(snapshot)
        return snapshot

    def load(self, *, task_id: str, user_id: str) -> PurchaseSessionSnapshot:
        return self._repository.load(task_id=task_id, user_id=user_id)

    def save_progress(
        self, snapshot: PurchaseSessionSnapshot
    ) -> PurchaseSessionSnapshot:
        self._repository.save(snapshot)
        return snapshot

    def update_context(
        self,
        *,
        task_id: str,
        user_id: str,
        context: PurchaseSessionContext,
    ) -> PurchaseSessionSnapshot:
        snapshot = self.load(task_id=task_id, user_id=user_id)
        updated = snapshot.model_copy(update={"context": context})
        self._repository.save(updated)
        return updated

    def attach_cart(
        self,
        *,
        task_id: str,
        user_id: str,
        store_id: str,
    ) -> PurchaseSessionSnapshot:
        snapshot = self.load(task_id=task_id, user_id=user_id)
        if snapshot.cart is not None:
            if snapshot.cart.store_id != store_id:
                raise AssistantCartStoreConflict(
                    "Purchase task is already attached to a different store"
                )
            return snapshot
        updated = snapshot.model_copy(update={"cart": AssistantCart(store_id=store_id)})
        self._repository.save(updated)
        return updated

    def add_product(
        self,
        *,
        task_id: str,
        user_id: str,
        product: ProductSnapshot,
        quantity: int,
        operation_id: str,
    ) -> PurchaseSessionSnapshot:
        return self._change_cart(
            task_id=task_id,
            user_id=user_id,
            change=lambda cart: cart.add(
                product,
                quantity=quantity,
                operation_id=operation_id,
            ),
        )

    def set_quantity(
        self,
        *,
        task_id: str,
        user_id: str,
        product_id: str,
        quantity: int,
        operation_id: str,
    ) -> PurchaseSessionSnapshot:
        return self._change_cart(
            task_id=task_id,
            user_id=user_id,
            change=lambda cart: cart.set_quantity(
                product_id,
                quantity=quantity,
                operation_id=operation_id,
            ),
        )

    def remove_product(
        self,
        *,
        task_id: str,
        user_id: str,
        product_id: str,
        operation_id: str,
    ) -> PurchaseSessionSnapshot:
        return self._change_cart(
            task_id=task_id,
            user_id=user_id,
            change=lambda cart: cart.remove(
                product_id,
                operation_id=operation_id,
            ),
        )

    def replace_product(
        self,
        *,
        task_id: str,
        user_id: str,
        product_id: str,
        replacement: ProductSnapshot,
        operation_id: str,
    ) -> PurchaseSessionSnapshot:
        return self._change_cart(
            task_id=task_id,
            user_id=user_id,
            change=lambda cart: cart.replace(
                product_id,
                replacement,
                operation_id=operation_id,
            ),
        )

    def _change_cart(
        self,
        *,
        task_id: str,
        user_id: str,
        change: Callable[[AssistantCart], AssistantCart],
    ) -> PurchaseSessionSnapshot:
        snapshot = self.load(task_id=task_id, user_id=user_id)
        if snapshot.cart is None:
            raise AssistantCartUnavailable(
                "Assistant cart is unavailable until a store is resolved"
            )
        cart = change(snapshot.cart)
        if cart == snapshot.cart:
            return snapshot
        machine = self._copy_machine(snapshot.state_machine)
        machine.cart_changed(version=cart.version)
        updated = snapshot.model_copy(
            update={"cart": cart, "state_machine": machine}
        )
        self._repository.save(updated)
        return updated

    @staticmethod
    def _copy_machine(machine: PurchaseStateMachine) -> PurchaseStateMachine:
        return PurchaseStateMachine(
            state=machine.state,
            cart_version=machine.cart_version,
            confirmation_id=machine.confirmation_id,
            confirmed_cart_version=machine.confirmed_cart_version,
        )
