from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pupu_assistant.domain.assistant_cart.models import ProductSnapshot
from pupu_assistant.domain.household import InventoryChange, PreferenceChange


class PurchaseIntent(StrEnum):
    SEARCH_PURCHASE = "search_purchase"
    BATCH_PURCHASE = "batch_purchase"
    REPURCHASE = "repurchase"
    RECIPE_PURCHASE = "recipe_purchase"
    DISH_RECOMMENDATION = "dish_recommendation"
    VIEW_CART = "view_cart"
    MODIFY_CART = "modify_cart"
    PREFERENCE_UPDATE = "preference_update"
    INVENTORY_UPDATE = "inventory_update"
    UNKNOWN = "unknown"


class RequirementPriority(StrEnum):
    VALUE_FOR_MONEY = "value_for_money"
    LOWEST_PRICE = "lowest_price"
    PREFERRED_BRAND = "preferred_brand"
    CLOSEST_SPECIFICATION = "closest_specification"


class PurchaseRequirement(BaseModel):
    """Platform-independent demand that must be matched to verified products."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    keywords: tuple[str, ...] = Field(min_length=1)
    quantity: int = Field(default=1, ge=1)
    target_specification: str | None = None
    preferred_brands: tuple[str, ...] = ()
    excluded_brands: tuple[str, ...] = ()
    max_price: Decimal | None = Field(default=None, ge=0)
    allow_substitution: bool = True
    priority: RequirementPriority = RequirementPriority.VALUE_FOR_MONEY

    @field_validator("keywords")
    @classmethod
    def reject_blank_keywords(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not keyword.strip() for keyword in value):
            raise ValueError("purchase keywords cannot be blank")
        return value


class PurchaseUnderstanding(BaseModel):
    """Structured result submitted by DeepSeek before product search begins."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: PurchaseIntent
    requirements: tuple[PurchaseRequirement, ...] = ()
    clarification_question: str | None = None
    dish_name: str | None = None
    servings: int | None = Field(default=None, ge=1)
    budget: Decimal | None = Field(default=None, ge=0)
    preference_changes: tuple[PreferenceChange, ...] = ()
    inventory_changes: tuple[InventoryChange, ...] = ()

    @field_validator("clarification_question")
    @classmethod
    def keep_one_concise_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        question = value.strip()
        if not question:
            raise ValueError("clarification question cannot be blank")
        if "\n" in question:
            raise ValueError("clarification must contain only one question")
        if question.count("?") + question.count("？") > 1:
            raise ValueError("clarification must contain only one question")
        return question

    @model_validator(mode="after")
    def require_actionable_purchase_input(self) -> PurchaseUnderstanding:
        if self.clarification_question and (
            self.preference_changes or self.inventory_changes
        ):
            raise ValueError("clarification cannot also mutate household memory")
        actionable_purchase_intents = {
            PurchaseIntent.SEARCH_PURCHASE,
            PurchaseIntent.BATCH_PURCHASE,
            PurchaseIntent.RECIPE_PURCHASE,
        }
        if (
            self.intent in actionable_purchase_intents
            and not self.requirements
            and self.clarification_question is None
        ):
            raise ValueError(
                "purchase intent requires requirements or clarification"
            )
        if self.intent is PurchaseIntent.PREFERENCE_UPDATE:
            if self.requirements:
                raise ValueError("preference update cannot include purchase requirements")
            if not self.preference_changes and self.clarification_question is None:
                raise ValueError(
                    "preference update requires changes or clarification"
                )
        elif self.preference_changes:
            raise ValueError("preference changes require preference_update intent")
        if self.intent is PurchaseIntent.INVENTORY_UPDATE:
            if self.requirements:
                raise ValueError("inventory update cannot include purchase requirements")
            if not self.inventory_changes and self.clarification_question is None:
                raise ValueError(
                    "inventory update requires changes or clarification"
                )
        elif self.inventory_changes:
            raise ValueError("inventory changes require inventory_update intent")
        return self


class ClarificationExchange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class ProductCandidate(BaseModel):
    """A requirement-to-product match backed by a Connector product fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: str = Field(min_length=1)
    product: ProductSnapshot
