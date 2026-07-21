from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from pupu_assistant.domain.assistant_cart.models import ProductSnapshot


class CachedProductFact(BaseModel):
    """A last-known Connector product snapshot; it is never presented as live data."""

    model_config = ConfigDict(frozen=True)

    product: ProductSnapshot
    image_url: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime


class ProductPricePoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    store_id: str = Field(min_length=1)
    store_product_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    price: Decimal = Field(ge=0)
    stock_available: bool
    captured_at: datetime


class ProductPriceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    store_id: str = Field(min_length=1)
    store_product_id: str = Field(min_length=1)
    current_price: Decimal = Field(ge=0)
    minimum_price: Decimal = Field(ge=0)
    maximum_price: Decimal = Field(ge=0)
    observation_count: int = Field(ge=1)
    first_captured_at: datetime
    last_captured_at: datetime


class OperationAuditEvent(BaseModel):
    """A redacted trace of an Agent, cart, confirmation, or external operation."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str | None = None
    event_type: str = Field(min_length=1)
    input_data: JsonValue | None = None
    output_data: JsonValue | None = None
    tool_name: str | None = None
    tool_result: JsonValue | None = None
    confirmation_id: str | None = None
    created_at: datetime
