from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductSnapshot(BaseModel):
    """A product fact captured from a platform response, never invented by the LLM."""

    model_config = ConfigDict(frozen=True)

    product_id: str = Field(min_length=1)
    store_product_id: str | None = None
    sku_id: str | None = None
    name: str = Field(min_length=1)
    specification: str = Field(min_length=1)
    unit_price: Decimal = Field(ge=0)
    stock_available: bool
    store_id: str = Field(min_length=1)
    captured_at: datetime
    source: Literal["pupu"]


class AssistantCartItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    product: ProductSnapshot
    quantity: int = Field(ge=1)

    @property
    def estimated_subtotal(self) -> Decimal:
        return self.product.unit_price * self.quantity
