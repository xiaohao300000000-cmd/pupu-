"""Persistence adapters for recoverable assistant state."""

from pupu_assistant.storage.household_memory_repository import (
    SqlAlchemyHouseholdMemoryRepository,
)
from pupu_assistant.storage.purchase_session_repository import (
    PurchaseSessionAlreadyExists,
    PurchaseSessionNotFound,
    PurchaseSessionOwnershipConflict,
    SqlAlchemyPurchaseSessionRepository,
)
from pupu_assistant.storage.product_catalog_repository import (
    SqlAlchemyProductCatalogRepository,
)

__all__ = [
    "PurchaseSessionAlreadyExists",
    "PurchaseSessionNotFound",
    "PurchaseSessionOwnershipConflict",
    "SqlAlchemyHouseholdMemoryRepository",
    "SqlAlchemyProductCatalogRepository",
    "SqlAlchemyPurchaseSessionRepository",
]
