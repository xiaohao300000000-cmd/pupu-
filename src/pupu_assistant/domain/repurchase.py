from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from pupu_assistant.domain.assistant_cart.models import ProductSnapshot


class RepurchaseLineStatus(StrEnum):
    UNCHANGED = "unchanged"
    PRICE_CHANGED = "price_changed"
    OUT_OF_STOCK = "out_of_stock"
    UNAVAILABLE = "unavailable"


class RepurchaseLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    store_product_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    specification: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    purchased_unit_price: Decimal = Field(ge=0)
    current_product: ProductSnapshot | None = None
    status: RepurchaseLineStatus
    price_delta: Decimal | None = None
    substitutes: tuple[ProductSnapshot, ...] = ()
    reason: str = Field(min_length=1)


class RepurchasePlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str = Field(min_length=1)
    purchased_at: datetime
    original_total: Decimal = Field(ge=0)
    current_estimated_total: Decimal = Field(ge=0)
    lines: tuple[RepurchaseLine, ...]

    @property
    def changed_count(self) -> int:
        return sum(
            line.status is not RepurchaseLineStatus.UNCHANGED
            for line in self.lines
        )

    @property
    def unavailable_count(self) -> int:
        return sum(
            line.status in {
                RepurchaseLineStatus.OUT_OF_STOCK,
                RepurchaseLineStatus.UNAVAILABLE,
            }
            for line in self.lines
        )
