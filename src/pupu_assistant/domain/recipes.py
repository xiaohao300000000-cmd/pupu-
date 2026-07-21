from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from pupu_assistant.domain.household import HouseholdInventoryItem
from pupu_assistant.domain.purchase.requirements import PurchaseRequirement


class InventoryIngredientUse(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: str = Field(min_length=1)
    ingredient_name: str = Field(min_length=1)
    used_quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1)


class InventoryIngredientReview(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: str = Field(min_length=1)
    ingredient_name: str = Field(min_length=1)
    recorded_quantity: Decimal = Field(ge=0)
    unit: str = Field(min_length=1)
    updated_at: datetime
    reason: str = Field(min_length=1)


class RecipeInventoryAdjustment(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirements: tuple[PurchaseRequirement, ...]
    inventory_used: tuple[InventoryIngredientUse, ...] = ()
    inventory_to_review: tuple[InventoryIngredientReview, ...] = ()


class RecipeInventoryService:
    """Subtracts only fresh, same-unit household inventory from recipe amounts."""

    def __init__(self, *, stale_after: timedelta = timedelta(days=5)) -> None:
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        self._stale_after = stale_after

    def adjust_requirements(
        self,
        *,
        requirements: tuple[PurchaseRequirement, ...],
        inventory: tuple[HouseholdInventoryItem, ...],
        as_of: datetime | None = None,
    ) -> RecipeInventoryAdjustment:
        as_of = self._as_utc(as_of or datetime.now(UTC))
        adjusted: list[PurchaseRequirement] = []
        used: list[InventoryIngredientUse] = []
        review: list[InventoryIngredientReview] = []
        inventory_by_name = {
            self._key(item.ingredient_name): item for item in inventory
        }

        for requirement in requirements:
            if (
                requirement.required_amount is None
                or requirement.required_unit is None
            ):
                adjusted.append(requirement)
                continue
            item = next(
                (
                    inventory_by_name[key]
                    for key in (
                        self._key(requirement.normalized_name),
                        *(self._key(keyword) for keyword in requirement.keywords),
                    )
                    if key in inventory_by_name
                ),
                None,
            )
            if item is None or item.quantity <= 0:
                adjusted.append(requirement)
                continue
            if self._key(item.unit) != self._key(requirement.required_unit):
                adjusted.append(requirement)
                continue
            item_updated_at = self._as_utc(item.updated_at)
            reason = self._review_reason(item, item_updated_at, as_of)
            if reason is not None:
                review.append(
                    InventoryIngredientReview(
                        requirement_id=requirement.requirement_id,
                        ingredient_name=item.ingredient_name,
                        recorded_quantity=item.quantity,
                        unit=item.unit,
                        updated_at=item_updated_at,
                        reason=reason,
                    )
                )
                adjusted.append(requirement)
                continue
            used_quantity = min(item.quantity, requirement.required_amount)
            if used_quantity > 0:
                used.append(
                    InventoryIngredientUse(
                        requirement_id=requirement.requirement_id,
                        ingredient_name=item.ingredient_name,
                        used_quantity=used_quantity,
                        unit=item.unit,
                    )
                )
            remaining = requirement.required_amount - used_quantity
            if remaining <= 0:
                continue
            adjusted.append(
                requirement.model_copy(
                    update={
                        "required_amount": remaining,
                        "target_specification": (
                            f"{self._quantity_text(remaining)} "
                            f"{requirement.required_unit}"
                        ),
                    }
                )
            )

        return RecipeInventoryAdjustment(
            requirements=tuple(adjusted),
            inventory_used=tuple(used),
            inventory_to_review=tuple(review),
        )

    def _review_reason(
        self,
        item: HouseholdInventoryItem,
        updated_at: datetime,
        as_of: datetime,
    ) -> str | None:
        if item.expires_at is not None and self._as_utc(item.expires_at) <= as_of:
            return "recorded inventory has reached its expected expiry"
        if as_of - updated_at > self._stale_after:
            return "recorded inventory is stale and was not deducted automatically"
        return None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _key(value: str) -> str:
        return value.strip().casefold()

    @staticmethod
    def _quantity_text(value: Decimal) -> str:
        return format(value.normalize(), "f")
