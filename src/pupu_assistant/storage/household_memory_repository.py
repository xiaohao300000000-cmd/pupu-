from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue
from sqlalchemy import (
    DateTime,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from pupu_assistant.domain.household import (
    HouseholdContextSnapshot,
    HouseholdInventoryItem,
    PreferenceType,
    UserPreference,
)


class HouseholdMemoryBase(DeclarativeBase):
    pass


class UserPreferenceRecord(HouseholdMemoryBase):
    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "preference_type",
            "target_key",
            name="uq_user_preference_target",
        ),
    )

    preference_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    preference_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_key: Mapped[str] = mapped_column(String(256), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class HouseholdInventoryRecord(HouseholdMemoryBase):
    __tablename__ = "household_inventory"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "ingredient_key",
            name="uq_user_inventory_ingredient",
        ),
    )

    inventory_item_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    ingredient_key: Mapped[str] = mapped_column(String(256), nullable=False)
    ingredient_name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(48), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class SqlAlchemyHouseholdMemoryRepository:
    """Stores user preferences and lightweight inventory in the project SQLite DB."""

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
        HouseholdMemoryBase.metadata.create_all(self._engine)

    def set_preference(
        self,
        *,
        user_id: str,
        preference_type: PreferenceType,
        target: str,
        value: JsonValue,
        confidence: Decimal = Decimal("1"),
        source: str = "user",
    ) -> UserPreference:
        user_id = self._required_text(user_id, field_name="user_id")
        target = self._required_text(target, field_name="target")
        source = self._required_text(source, field_name="source")
        confidence = self._confidence(confidence)
        target_key = self._normalized_key(target)
        value_json = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        now = datetime.now(UTC)
        with self._session_factory.begin() as session:
            record = session.scalar(
                select(UserPreferenceRecord).where(
                    UserPreferenceRecord.user_id == user_id,
                    UserPreferenceRecord.preference_type == preference_type.value,
                    UserPreferenceRecord.target_key == target_key,
                )
            )
            if record is None:
                record = UserPreferenceRecord(
                    preference_id=uuid4().hex,
                    user_id=user_id,
                    preference_type=preference_type.value,
                    target_key=target_key,
                    target=target,
                    value_json=value_json,
                    confidence=confidence,
                    source=source,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.target = target
                record.value_json = value_json
                record.confidence = confidence
                record.source = source
                record.updated_at = now
            session.flush()
            return self._preference(record)

    def list_preferences(self, *, user_id: str) -> tuple[UserPreference, ...]:
        user_id = self._required_text(user_id, field_name="user_id")
        with self._session_factory() as session:
            records = session.scalars(
                select(UserPreferenceRecord)
                .where(UserPreferenceRecord.user_id == user_id)
                .order_by(
                    UserPreferenceRecord.preference_type,
                    UserPreferenceRecord.target_key,
                )
            ).all()
            return tuple(self._preference(record) for record in records)

    def delete_preference(
        self,
        *,
        user_id: str,
        preference_type: PreferenceType,
        target: str,
    ) -> bool:
        user_id = self._required_text(user_id, field_name="user_id")
        target_key = self._normalized_key(target)
        with self._session_factory.begin() as session:
            result = session.execute(
                delete(UserPreferenceRecord).where(
                    UserPreferenceRecord.user_id == user_id,
                    UserPreferenceRecord.preference_type == preference_type.value,
                    UserPreferenceRecord.target_key == target_key,
                )
            )
            return bool(result.rowcount)

    def upsert_inventory_item(
        self,
        *,
        user_id: str,
        ingredient_name: str,
        quantity: Decimal,
        unit: str,
        confidence: Decimal = Decimal("1"),
        source: str = "user",
        expires_at: datetime | None = None,
    ) -> HouseholdInventoryItem:
        user_id = self._required_text(user_id, field_name="user_id")
        ingredient_name = self._required_text(
            ingredient_name,
            field_name="ingredient_name",
        )
        unit = self._required_text(unit, field_name="unit")
        source = self._required_text(source, field_name="source")
        quantity = Decimal(quantity)
        if quantity < 0:
            raise ValueError("quantity must be zero or greater")
        confidence = self._confidence(confidence)
        ingredient_key = self._normalized_key(ingredient_name)
        now = datetime.now(UTC)
        with self._session_factory.begin() as session:
            record = session.scalar(
                select(HouseholdInventoryRecord).where(
                    HouseholdInventoryRecord.user_id == user_id,
                    HouseholdInventoryRecord.ingredient_key == ingredient_key,
                )
            )
            if record is None:
                record = HouseholdInventoryRecord(
                    inventory_item_id=uuid4().hex,
                    user_id=user_id,
                    ingredient_key=ingredient_key,
                    ingredient_name=ingredient_name,
                    quantity=quantity,
                    unit=unit,
                    confidence=confidence,
                    source=source,
                    updated_at=now,
                    expires_at=expires_at,
                )
                session.add(record)
            else:
                record.ingredient_name = ingredient_name
                record.quantity = quantity
                record.unit = unit
                record.confidence = confidence
                record.source = source
                record.updated_at = now
                record.expires_at = expires_at
            session.flush()
            return self._inventory_item(record)

    def list_inventory(
        self,
        *,
        user_id: str,
    ) -> tuple[HouseholdInventoryItem, ...]:
        user_id = self._required_text(user_id, field_name="user_id")
        with self._session_factory() as session:
            records = session.scalars(
                select(HouseholdInventoryRecord)
                .where(HouseholdInventoryRecord.user_id == user_id)
                .order_by(HouseholdInventoryRecord.ingredient_key)
            ).all()
            return tuple(self._inventory_item(record) for record in records)

    def delete_inventory_item(
        self,
        *,
        user_id: str,
        ingredient_name: str,
    ) -> bool:
        user_id = self._required_text(user_id, field_name="user_id")
        ingredient_key = self._normalized_key(ingredient_name)
        with self._session_factory.begin() as session:
            result = session.execute(
                delete(HouseholdInventoryRecord).where(
                    HouseholdInventoryRecord.user_id == user_id,
                    HouseholdInventoryRecord.ingredient_key == ingredient_key,
                )
            )
            return bool(result.rowcount)

    def snapshot(self, *, user_id: str) -> HouseholdContextSnapshot:
        user_id = self._required_text(user_id, field_name="user_id")
        return HouseholdContextSnapshot(
            user_id=user_id,
            preferences=self.list_preferences(user_id=user_id),
            inventory=self.list_inventory(user_id=user_id),
        )

    def close(self) -> None:
        self._engine.dispose()

    @staticmethod
    def _preference(record: UserPreferenceRecord) -> UserPreference:
        return UserPreference(
            preference_id=record.preference_id,
            user_id=record.user_id,
            preference_type=PreferenceType(record.preference_type),
            target=record.target,
            value=json.loads(record.value_json),
            confidence=record.confidence,
            source=record.source,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _inventory_item(
        record: HouseholdInventoryRecord,
    ) -> HouseholdInventoryItem:
        return HouseholdInventoryItem(
            inventory_item_id=record.inventory_item_id,
            user_id=record.user_id,
            ingredient_name=record.ingredient_name,
            quantity=record.quantity,
            unit=record.unit,
            confidence=record.confidence,
            source=record.source,
            updated_at=record.updated_at,
            expires_at=record.expires_at,
        )

    @staticmethod
    def _required_text(value: str, *, field_name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")
        return normalized

    @classmethod
    def _normalized_key(cls, value: str) -> str:
        return cls._required_text(value, field_name="key").casefold()

    @staticmethod
    def _confidence(value: Decimal) -> Decimal:
        confidence = Decimal(value)
        if confidence < 0 or confidence > 1:
            raise ValueError("confidence must be between zero and one")
        return confidence
