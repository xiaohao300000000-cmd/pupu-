from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue
from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from pupu_assistant.domain.assistant_cart.models import ProductSnapshot
from pupu_assistant.domain.catalog import (
    CachedProductFact,
    OperationAuditEvent,
    ProductPricePoint,
    ProductPriceSummary,
    ShoppingHistoryEntry,
)


class ProductCatalogBase(DeclarativeBase):
    pass


class ProductCacheRecord(ProductCatalogBase):
    __tablename__ = "product_cache"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "store_id",
            "store_product_id",
            name="uq_product_cache_platform_store_product",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    store_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    store_product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sku_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    specification: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    stock_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductPriceHistoryRecord(ProductCatalogBase):
    __tablename__ = "product_price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    store_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    store_product_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    stock_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperationAuditRecord(ProductCatalogBase):
    __tablename__ = "operation_logs"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ShoppingHistoryCacheRecord(ProductCatalogBase):
    __tablename__ = "shopping_history_cache"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "order_id",
            "store_product_id",
            name="uq_shopping_history_order_product",
        ),
    )

    history_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    order_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    store_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    store_product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    specification: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    purchased_unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )
    purchased_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class SqlAlchemyProductCatalogRepository:
    """Persists last-known product facts, price observations, and redacted audits."""

    def __init__(self, database_path: Path | str) -> None:
        self._database_path = Path(database_path)
        if self._database_path == Path(":memory:"):
            database_url = "sqlite+pysqlite:///:memory:"
        else:
            resolved = self._database_path.expanduser().resolve()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            database_url = f"sqlite+pysqlite:///{resolved}"
        self._engine = create_engine(database_url)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        ProductCatalogBase.metadata.create_all(self._engine)

    def record_product(
        self,
        product: ProductSnapshot,
        *,
        image_url: str | None = None,
    ) -> CachedProductFact:
        store_product_id = self._required_store_product_id(product)
        captured_at = self._as_utc(product.captured_at)
        with self._session_factory.begin() as session:
            record = session.scalar(
                select(ProductCacheRecord).where(
                    ProductCacheRecord.platform == product.source,
                    ProductCacheRecord.store_id == product.store_id,
                    ProductCacheRecord.store_product_id == store_product_id,
                )
            )
            if record is None:
                record = ProductCacheRecord(
                    platform=product.source,
                    store_id=product.store_id,
                    store_product_id=store_product_id,
                    product_id=product.product_id,
                    sku_id=product.sku_id,
                    product_name=product.name,
                    specification=product.specification,
                    price=product.unit_price,
                    stock_available=product.stock_available,
                    image_url=image_url,
                    captured_at=captured_at,
                    first_seen_at=captured_at,
                    last_seen_at=captured_at,
                )
                session.add(record)
            else:
                record.product_id = product.product_id
                record.sku_id = product.sku_id
                record.product_name = product.name
                record.specification = product.specification
                record.price = product.unit_price
                record.stock_available = product.stock_available
                record.image_url = image_url or record.image_url
                record.captured_at = captured_at
                record.last_seen_at = max(
                    self._as_utc(record.last_seen_at),
                    captured_at,
                )
            session.add(
                ProductPriceHistoryRecord(
                    platform=product.source,
                    store_id=product.store_id,
                    store_product_id=store_product_id,
                    product_id=product.product_id,
                    product_name=product.name,
                    price=product.unit_price,
                    stock_available=product.stock_available,
                    captured_at=captured_at,
                )
            )
            session.flush()
            return self._cached_product(record)

    def search_cached_products(
        self,
        *,
        store_id: str,
        query: str,
        limit: int = 3,
    ) -> tuple[CachedProductFact, ...]:
        store_id = self._required_text(store_id, field_name="store_id")
        query = self._required_text(query, field_name="query")
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        with self._session_factory() as session:
            records = session.scalars(
                select(ProductCacheRecord)
                .where(
                    ProductCacheRecord.store_id == store_id,
                    ProductCacheRecord.product_name.contains(query),
                )
                .order_by(ProductCacheRecord.last_seen_at.desc())
                .limit(limit)
            ).all()
            return tuple(self._cached_product(record) for record in records)

    def list_price_history(
        self,
        *,
        store_id: str,
        store_product_id: str,
        limit: int = 100,
    ) -> tuple[ProductPricePoint, ...]:
        store_id = self._required_text(store_id, field_name="store_id")
        store_product_id = self._required_text(
            store_product_id,
            field_name="store_product_id",
        )
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._session_factory() as session:
            records = session.scalars(
                select(ProductPriceHistoryRecord)
                .where(
                    ProductPriceHistoryRecord.store_id == store_id,
                    ProductPriceHistoryRecord.store_product_id == store_product_id,
                )
                .order_by(ProductPriceHistoryRecord.captured_at.desc())
                .limit(limit)
            ).all()
            return tuple(self._price_point(record) for record in records)

    def get_price_summary(
        self,
        *,
        store_id: str,
        store_product_id: str,
    ) -> ProductPriceSummary | None:
        history = self.list_price_history(
            store_id=store_id,
            store_product_id=store_product_id,
            limit=1000,
        )
        if not history:
            return None
        prices = tuple(point.price for point in history)
        latest = history[0]
        earliest = history[-1]
        return ProductPriceSummary(
            store_id=store_id,
            store_product_id=store_product_id,
            current_price=latest.price,
            minimum_price=min(prices),
            maximum_price=max(prices),
            observation_count=len(history),
            first_captured_at=earliest.captured_at,
            last_captured_at=latest.captured_at,
        )

    def append_operation(
        self,
        *,
        user_id: str,
        event_type: str,
        session_id: str | None = None,
        input_data: JsonValue | None = None,
        output_data: JsonValue | None = None,
        tool_name: str | None = None,
        tool_result: JsonValue | None = None,
        confirmation_id: str | None = None,
        event_id: str | None = None,
        created_at: datetime | None = None,
    ) -> OperationAuditEvent:
        user_id = self._required_text(user_id, field_name="user_id")
        event_type = self._required_text(event_type, field_name="event_type")
        event_id = event_id or uuid4().hex
        created_at = created_at or datetime.now(UTC)
        with self._session_factory.begin() as session:
            existing = session.get(OperationAuditRecord, event_id)
            if existing is not None:
                if existing.user_id != user_id:
                    raise ValueError("operation event belongs to another user")
                if existing.event_type != event_type:
                    raise ValueError("operation event id was reused for another event")
                return self._audit_event(existing)
            record = OperationAuditRecord(
                event_id=event_id,
                user_id=user_id,
                session_id=session_id,
                event_type=event_type,
                input_json=self._json(input_data),
                output_json=self._json(output_data),
                tool_name=tool_name,
                tool_result_json=self._json(tool_result),
                confirmation_id=confirmation_id,
                created_at=created_at,
            )
            session.add(record)
            session.flush()
            return self._audit_event(record)

    def list_operations(
        self,
        *,
        user_id: str,
        limit: int = 100,
    ) -> tuple[OperationAuditEvent, ...]:
        user_id = self._required_text(user_id, field_name="user_id")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._session_factory() as session:
            records = session.scalars(
                select(OperationAuditRecord)
                .where(OperationAuditRecord.user_id == user_id)
                .order_by(OperationAuditRecord.created_at.desc())
                .limit(limit)
            ).all()
            return tuple(self._audit_event(record) for record in records)

    def cache_purchase(
        self,
        *,
        user_id: str,
        order_id: str,
        store_id: str,
        product_id: str,
        store_product_id: str,
        product_name: str,
        specification: str,
        quantity: int,
        purchased_unit_price: Decimal,
        purchased_at: datetime,
    ) -> ShoppingHistoryEntry:
        user_id = self._required_text(user_id, field_name="user_id")
        order_id = self._required_text(order_id, field_name="order_id")
        store_id = self._required_text(store_id, field_name="store_id")
        product_id = self._required_text(product_id, field_name="product_id")
        store_product_id = self._required_text(
            store_product_id,
            field_name="store_product_id",
        )
        product_name = self._required_text(product_name, field_name="product_name")
        specification = self._required_text(
            specification,
            field_name="specification",
        )
        if quantity < 1:
            raise ValueError("quantity must be at least one")
        purchased_unit_price = Decimal(purchased_unit_price)
        if purchased_unit_price < 0:
            raise ValueError("purchased_unit_price cannot be negative")
        purchased_at = self._as_utc(purchased_at)
        now = datetime.now(UTC)
        with self._session_factory.begin() as session:
            record = session.scalar(
                select(ShoppingHistoryCacheRecord).where(
                    ShoppingHistoryCacheRecord.user_id == user_id,
                    ShoppingHistoryCacheRecord.order_id == order_id,
                    ShoppingHistoryCacheRecord.store_product_id == store_product_id,
                )
            )
            if record is None:
                record = ShoppingHistoryCacheRecord(
                    history_id=uuid4().hex,
                    user_id=user_id,
                    order_id=order_id,
                    store_id=store_id,
                    product_id=product_id,
                    store_product_id=store_product_id,
                    product_name=product_name,
                    specification=specification,
                    quantity=quantity,
                    purchased_unit_price=purchased_unit_price,
                    purchased_at=purchased_at,
                    cached_at=now,
                )
                session.add(record)
            else:
                record.store_id = store_id
                record.product_id = product_id
                record.product_name = product_name
                record.specification = specification
                record.quantity = quantity
                record.purchased_unit_price = purchased_unit_price
                record.purchased_at = purchased_at
                record.cached_at = now
            session.flush()
            return self._shopping_history(record)

    def list_shopping_history(
        self,
        *,
        user_id: str,
        limit: int = 100,
    ) -> tuple[ShoppingHistoryEntry, ...]:
        user_id = self._required_text(user_id, field_name="user_id")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._session_factory() as session:
            records = session.scalars(
                select(ShoppingHistoryCacheRecord)
                .where(ShoppingHistoryCacheRecord.user_id == user_id)
                .order_by(ShoppingHistoryCacheRecord.purchased_at.desc())
                .limit(limit)
            ).all()
            return tuple(self._shopping_history(record) for record in records)

    def clear_shopping_history(self, *, user_id: str) -> int:
        user_id = self._required_text(user_id, field_name="user_id")
        with self._session_factory.begin() as session:
            result = session.execute(
                delete(ShoppingHistoryCacheRecord).where(
                    ShoppingHistoryCacheRecord.user_id == user_id
                )
            )
            return int(result.rowcount or 0)

    def close(self) -> None:
        self._engine.dispose()

    @staticmethod
    def _required_store_product_id(product: ProductSnapshot) -> str:
        if not product.store_product_id:
            raise ValueError("cached product requires store_product_id")
        return product.store_product_id

    @staticmethod
    def _required_text(value: str, *, field_name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")
        return normalized

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _cached_product(record: ProductCacheRecord) -> CachedProductFact:
        return CachedProductFact(
            product=ProductSnapshot(
                product_id=record.product_id,
                store_product_id=record.store_product_id,
                sku_id=record.sku_id,
                name=record.product_name,
                specification=record.specification,
                unit_price=record.price,
                stock_available=record.stock_available,
                store_id=record.store_id,
                captured_at=record.captured_at,
                source="pupu",
            ),
            image_url=record.image_url,
            first_seen_at=record.first_seen_at,
            last_seen_at=record.last_seen_at,
        )

    @staticmethod
    def _price_point(record: ProductPriceHistoryRecord) -> ProductPricePoint:
        return ProductPricePoint(
            store_id=record.store_id,
            store_product_id=record.store_product_id,
            product_id=record.product_id,
            product_name=record.product_name,
            price=record.price,
            stock_available=record.stock_available,
            captured_at=record.captured_at,
        )

    @staticmethod
    def _shopping_history(
        record: ShoppingHistoryCacheRecord,
    ) -> ShoppingHistoryEntry:
        return ShoppingHistoryEntry(
            history_id=record.history_id,
            user_id=record.user_id,
            order_id=record.order_id,
            store_id=record.store_id,
            product_id=record.product_id,
            store_product_id=record.store_product_id,
            product_name=record.product_name,
            specification=record.specification,
            quantity=record.quantity,
            purchased_unit_price=record.purchased_unit_price,
            purchased_at=record.purchased_at,
            cached_at=record.cached_at,
        )

    @classmethod
    def _audit_event(cls, record: OperationAuditRecord) -> OperationAuditEvent:
        return OperationAuditEvent(
            event_id=record.event_id,
            user_id=record.user_id,
            session_id=record.session_id,
            event_type=record.event_type,
            input_data=cls._loads(record.input_json),
            output_data=cls._loads(record.output_json),
            tool_name=record.tool_name,
            tool_result=cls._loads(record.tool_result_json),
            confirmation_id=record.confirmation_id,
            created_at=record.created_at,
        )

    @classmethod
    def _json(cls, value: JsonValue | None) -> str | None:
        if value is None:
            return None
        return json.dumps(
            cls._redact(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    @staticmethod
    def _loads(value: str | None) -> JsonValue | None:
        if value is None:
            return None
        return json.loads(value)

    @classmethod
    def _redact(cls, value: JsonValue, *, field_name: str = "") -> JsonValue:
        if field_name and any(
            marker in field_name.casefold()
            for marker in (
                "token",
                "authorization",
                "secret",
                "password",
                "phone",
                "mobile",
                "address",
            )
        ):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {
                key: cls._redact(item, field_name=key)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        if isinstance(value, str):
            redacted = re.sub(
                r"(?i)bearer\s+[a-z0-9._~+/=-]+",
                "Bearer [REDACTED]",
                value,
            )
            return re.sub(r"(?<!\d)1\d{10}(?!\d)", "[REDACTED_PHONE]", redacted)
        return value
