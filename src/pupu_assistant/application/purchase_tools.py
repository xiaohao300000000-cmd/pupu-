from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pupu_assistant.application.purchase_sessions import PurchaseSessionService
from pupu_assistant.application.tool_registry import (
    ToolRegistry,
    ToolRisk,
    ToolSpec,
)
from pupu_assistant.domain.assistant_cart.models import ProductSnapshot
from pupu_assistant.integrations.pupu.connector import (
    PupuConnector,
    PupuConnectorContractViolation,
)


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchProductsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    max_results: int = Field(default=3, ge=1, le=3)


class ProductDetailArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: str = Field(min_length=1)
    store_product_id: str = Field(min_length=1)


class CartAddArguments(ProductDetailArguments):
    quantity: int = Field(ge=1)
    operation_id: str = Field(min_length=1)


class CartQuantityArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    operation_id: str = Field(min_length=1)


class CartRemoveArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)


class CartReplaceArguments(ProductDetailArguments):
    product_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)


class PurchaseToolset:
    """Binds one user's recoverable task to safe Connector and cart tools."""

    def __init__(
        self,
        *,
        connector: PupuConnector,
        sessions: PurchaseSessionService,
        task_id: str,
        user_id: str,
    ) -> None:
        self._connector = connector
        self._sessions = sessions
        self._task_id = task_id
        self._user_id = user_id

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="get_current_store",
                description="Get the user's current Pupu store without exposing address details",
                arguments_model=EmptyArguments,
                handler=self._get_current_store,
                risk=ToolRisk.READ_ONLY,
            )
        )
        registry.register(
            ToolSpec(
                name="search_products",
                description="Search verified products in the current Pupu store",
                arguments_model=SearchProductsArguments,
                handler=self._search_products,
                risk=ToolRisk.READ_ONLY,
            )
        )
        registry.register(
            ToolSpec(
                name="get_product_detail",
                description="Read current price, stock, and specification for a product",
                arguments_model=ProductDetailArguments,
                handler=self._get_product_detail,
                risk=ToolRisk.READ_ONLY,
            )
        )
        registry.register(
            ToolSpec(
                name="assistant_cart.get",
                description="Read the independent assistant cart",
                arguments_model=EmptyArguments,
                handler=self._get_cart,
                risk=ToolRisk.ASSISTANT_CART,
            )
        )
        registry.register(
            ToolSpec(
                name="assistant_cart.add",
                description="Add a Connector-verified product to the assistant cart",
                arguments_model=CartAddArguments,
                handler=self._add_product,
                risk=ToolRisk.ASSISTANT_CART,
            )
        )
        registry.register(
            ToolSpec(
                name="assistant_cart.set_quantity",
                description="Set a product quantity in the assistant cart",
                arguments_model=CartQuantityArguments,
                handler=self._set_quantity,
                risk=ToolRisk.ASSISTANT_CART,
            )
        )
        registry.register(
            ToolSpec(
                name="assistant_cart.remove",
                description="Remove a product from the assistant cart",
                arguments_model=CartRemoveArguments,
                handler=self._remove_product,
                risk=ToolRisk.ASSISTANT_CART,
            )
        )
        registry.register(
            ToolSpec(
                name="assistant_cart.replace",
                description="Replace a cart product with a Connector-verified product",
                arguments_model=CartReplaceArguments,
                handler=self._replace_product,
                risk=ToolRisk.ASSISTANT_CART,
            )
        )
        return registry

    async def _get_current_store(self, arguments: EmptyArguments):
        del arguments
        store = await self._connector.get_current_store(user_id=self._user_id)
        self._sessions.attach_cart(
            task_id=self._task_id,
            user_id=self._user_id,
            store_id=store.store_id,
        )
        return store

    async def _search_products(self, arguments: SearchProductsArguments):
        products = await self._connector.search_products(
            user_id=self._user_id,
            query=arguments.query,
            store_id=arguments.store_id,
            limit=arguments.max_results,
        )
        verified = [
            self._verified_product(product, store_id=arguments.store_id)
            for product in products
        ]
        return {
            "search_scope": "verified_connector",
            "products": verified[: arguments.max_results],
        }

    async def _get_product_detail(self, arguments: ProductDetailArguments):
        product = await self._connector.get_product_detail(
            user_id=self._user_id,
            store_id=arguments.store_id,
            store_product_id=arguments.store_product_id,
        )
        return self._verified_product(
            product,
            store_id=arguments.store_id,
            store_product_id=arguments.store_product_id,
        )

    def _get_cart(self, arguments: EmptyArguments):
        del arguments
        snapshot = self._sessions.load(
            task_id=self._task_id,
            user_id=self._user_id,
        )
        return snapshot.cart

    async def _add_product(self, arguments: CartAddArguments):
        product = await self._connector.get_product_detail(
            user_id=self._user_id,
            store_id=arguments.store_id,
            store_product_id=arguments.store_product_id,
        )
        product = self._verified_product(
            product,
            store_id=arguments.store_id,
            store_product_id=arguments.store_product_id,
        )
        return self._sessions.add_product(
            task_id=self._task_id,
            user_id=self._user_id,
            product=product,
            quantity=arguments.quantity,
            operation_id=arguments.operation_id,
        ).cart

    def _set_quantity(self, arguments: CartQuantityArguments):
        return self._sessions.set_quantity(
            task_id=self._task_id,
            user_id=self._user_id,
            product_id=arguments.product_id,
            quantity=arguments.quantity,
            operation_id=arguments.operation_id,
        ).cart

    def _remove_product(self, arguments: CartRemoveArguments):
        return self._sessions.remove_product(
            task_id=self._task_id,
            user_id=self._user_id,
            product_id=arguments.product_id,
            operation_id=arguments.operation_id,
        ).cart

    async def _replace_product(self, arguments: CartReplaceArguments):
        replacement = await self._connector.get_product_detail(
            user_id=self._user_id,
            store_id=arguments.store_id,
            store_product_id=arguments.store_product_id,
        )
        replacement = self._verified_product(
            replacement,
            store_id=arguments.store_id,
            store_product_id=arguments.store_product_id,
        )
        return self._sessions.replace_product(
            task_id=self._task_id,
            user_id=self._user_id,
            product_id=arguments.product_id,
            replacement=replacement,
            operation_id=arguments.operation_id,
        ).cart

    @staticmethod
    def _verified_product(
        product: ProductSnapshot,
        *,
        store_id: str,
        store_product_id: str | None = None,
    ) -> ProductSnapshot:
        if product.store_id != store_id:
            raise PupuConnectorContractViolation(
                "Connector returned a product from a different store"
            )
        if not product.store_product_id:
            raise PupuConnectorContractViolation(
                "Connector product is missing store_product_id"
            )
        if (
            store_product_id is not None
            and product.store_product_id != store_product_id
        ):
            raise PupuConnectorContractViolation(
                "Connector returned a different store product"
            )
        return product
