from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pupu_assistant.domain.cart_write import (
    CartMutationTimeout,
    CartWriteOperation,
    PlatformCartState,
    validate_preview,
)
from pupu_assistant.storage.confirmation_store import ConfirmationStore


class LiveMutationDisabled(RuntimeError):
    pass


class CartGateway(Protocol):
    async def read_state(self, product_ids: set[str]) -> PlatformCartState: ...

    async def set_absolute_quantities(
        self,
        operations: Sequence[CartWriteOperation],
        *,
        idempotency_key: str,
    ) -> None: ...


class CartExecutionStatus(StrEnum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CartExecutionResult:
    status: CartExecutionStatus
    quantities: dict[str, int]
    mutation_timed_out: bool


class CartControl:
    def __init__(
        self,
        *,
        gateway: CartGateway,
        confirmations: ConfirmationStore,
        live_mutation_allowed: bool,
    ) -> None:
        self._gateway = gateway
        self._confirmations = confirmations
        self._live_mutation_allowed = live_mutation_allowed

    async def execute(
        self,
        confirmation_id: str,
        *,
        phrase: str,
        now: datetime,
    ) -> CartExecutionResult:
        if not self._live_mutation_allowed:
            raise LiveMutationDisabled("Live Pupu cart mutation is disabled")

        stored = self._confirmations.get(confirmation_id)
        preview = stored.preview
        product_ids = {operation.product_id for operation in preview.operations}
        current_state = await self._gateway.read_state(product_ids)
        validate_preview(preview, current_state)
        preview = self._confirmations.consume(
            confirmation_id,
            phrase=phrase,
            now=now,
        )

        timed_out = False
        try:
            await self._gateway.set_absolute_quantities(
                preview.operations,
                idempotency_key=preview.idempotency_key,
            )
        except CartMutationTimeout:
            timed_out = True

        readback = await self._gateway.read_state(product_ids)
        quantities = {
            product_id: readback.quantities.get(product_id, 0)
            for product_id in product_ids
        }
        matches = readback.store_id == preview.store_id and all(
            quantities[operation.product_id] == operation.target_quantity
            for operation in preview.operations
        )
        if matches:
            status = CartExecutionStatus.VERIFIED
        elif timed_out:
            status = CartExecutionStatus.UNKNOWN
        else:
            status = CartExecutionStatus.MISMATCH
        return CartExecutionResult(
            status=status,
            quantities=quantities,
            mutation_timed_out=timed_out,
        )
