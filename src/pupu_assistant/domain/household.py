from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class PreferenceType(StrEnum):
    HOUSEHOLD_SIZE = "household_size"
    PREFERRED_BRAND = "preferred_brand"
    EXCLUDED_BRAND = "excluded_brand"
    PACKAGE_PREFERENCE = "package_preference"
    PRICE_SENSITIVITY = "price_sensitivity"
    DIETARY_RESTRICTION = "dietary_restriction"
    ALLERGEN = "allergen"
    DISLIKED_INGREDIENT = "disliked_ingredient"
    SUBSTITUTION_POLICY = "substitution_policy"
    PRODUCT_ALIAS = "product_alias"


class PreferenceChange(BaseModel):
    """A user-requested preference mutation extracted from one message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    preference_type: PreferenceType
    target: str = Field(min_length=1)
    value: JsonValue | None = None
    delete: bool = False
    confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)

    @model_validator(mode="after")
    def require_value_for_set(self) -> PreferenceChange:
        if self.delete and self.value is not None:
            raise ValueError("deleted preference cannot include a value")
        if not self.delete and self.value is None:
            raise ValueError("preference value is required")
        return self


class InventoryChange(BaseModel):
    """A user-requested lightweight inventory mutation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ingredient_name: str = Field(min_length=1)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = None
    delete: bool = False
    confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)

    @model_validator(mode="after")
    def require_quantity_and_unit_for_upsert(self) -> InventoryChange:
        if self.delete and (self.quantity is not None or self.unit is not None):
            raise ValueError("deleted inventory item cannot include quantity or unit")
        if not self.delete and (self.quantity is None or not self.unit):
            raise ValueError("inventory quantity and unit are required")
        return self


class UserPreference(BaseModel):
    """One user-controlled preference safe for household purchase planning."""

    model_config = ConfigDict(frozen=True)

    preference_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    preference_type: PreferenceType
    target: str = Field(min_length=1)
    value: JsonValue
    confidence: Decimal = Field(ge=0, le=1)
    source: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime


class HouseholdInventoryItem(BaseModel):
    """A lightweight, user-scoped estimate rather than a platform stock fact."""

    model_config = ConfigDict(frozen=True)

    inventory_item_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    ingredient_name: str = Field(min_length=1)
    quantity: Decimal = Field(ge=0)
    unit: str = Field(min_length=1)
    confidence: Decimal = Field(ge=0, le=1)
    source: str = Field(min_length=1)
    updated_at: datetime
    expires_at: datetime | None = None


class HouseholdContextSnapshot(BaseModel):
    """Preferences and inventory that may be supplied to the purchase Agent."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1)
    preferences: tuple[UserPreference, ...] = ()
    inventory: tuple[HouseholdInventoryItem, ...] = ()

    def to_agent_context(self) -> dict[str, object]:
        """Exclude internal IDs and the platform user identifier from model context."""

        return {
            "preferences": [
                {
                    "type": preference.preference_type.value,
                    "target": preference.target,
                    "value": preference.value,
                    "confidence": str(preference.confidence),
                    "source": preference.source,
                }
                for preference in self.preferences
            ],
            "inventory": [
                {
                    "ingredient_name": item.ingredient_name,
                    "quantity": str(item.quantity),
                    "unit": item.unit,
                    "confidence": str(item.confidence),
                    "source": item.source,
                    "updated_at": item.updated_at.isoformat(),
                    "expires_at": (
                        item.expires_at.isoformat() if item.expires_at else None
                    ),
                }
                for item in self.inventory
            ],
        }
