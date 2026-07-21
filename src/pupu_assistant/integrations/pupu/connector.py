from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from pupu_assistant.domain.assistant_cart.models import ProductSnapshot


class PupuConnectorError(RuntimeError):
    pass


class PupuConnectorContractViolation(PupuConnectorError):
    pass


class PupuConnectorUnavailable(PupuConnectorError):
    pass


class PupuConnectorAuthenticationRequired(PupuConnectorError):
    pass


class StoreContext(BaseModel):
    """Non-sensitive store facts safe to expose to the purchase Agent."""

    model_config = ConfigDict(frozen=True)

    address_id: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    place_id: str = Field(min_length=1)
    city_zip: str = Field(min_length=1)
    display_name: str | None = None


class PupuConnector(Protocol):
    """Stable platform boundary; implementations keep credentials private."""

    async def get_current_store(self, *, user_id: str) -> StoreContext: ...

    async def search_products(
        self,
        *,
        user_id: str,
        query: str,
        store_id: str,
        limit: int,
    ) -> Sequence[ProductSnapshot]: ...

    async def get_product_detail(
        self,
        *,
        user_id: str,
        store_id: str,
        store_product_id: str,
    ) -> ProductSnapshot: ...
