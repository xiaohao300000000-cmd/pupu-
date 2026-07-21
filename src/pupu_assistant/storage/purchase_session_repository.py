from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
    delete,
    event,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from pupu_assistant.application.state_machine import PurchaseState, PurchaseStateMachine
from pupu_assistant.domain.assistant_cart.models import (
    AssistantCartItem,
    ProductSnapshot,
)
from pupu_assistant.domain.assistant_cart.service import AssistantCart
from pupu_assistant.domain.purchase.session import (
    PurchaseSessionContext,
    PurchaseSessionSnapshot,
)


class PurchaseSessionRepositoryError(RuntimeError):
    pass


class PurchaseSessionNotFound(PurchaseSessionRepositoryError):
    pass


class PurchaseSessionAlreadyExists(PurchaseSessionRepositoryError):
    pass


class PurchaseSessionOwnershipConflict(PurchaseSessionRepositoryError):
    pass


class Base(DeclarativeBase):
    pass


class PurchaseSessionRecord(Base):
    __tablename__ = "purchase_sessions"

    task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False)
    store_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cart_version: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_cart_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    applied_operation_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    items: Mapped[list[AssistantCartItemRecord]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AssistantCartItemRecord.product_id",
    )


class AssistantCartItemRecord(Base):
    __tablename__ = "assistant_cart_items"

    task_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("purchase_sessions.task_id", ondelete="CASCADE"),
        primary_key=True,
    )
    product_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    store_product_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sku_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    specification: Mapped[str] = mapped_column(Text, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    stock_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    store_id: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at_iso: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    session: Mapped[PurchaseSessionRecord] = relationship(back_populates="items")


class SqlAlchemyPurchaseSessionRepository:
    """Atomically stores one user's task state and independent assistant cart."""

    def __init__(self, database_path: Path | str) -> None:
        self._database_path = Path(database_path)
        if self._database_path == Path(":memory:"):
            database_url = "sqlite+pysqlite:///:memory:"
        else:
            resolved = self._database_path.expanduser().resolve()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            database_url = f"sqlite+pysqlite:///{resolved}"

        self._engine = create_engine(database_url)
        event.listen(self._engine, "connect", self._enable_foreign_keys)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        Base.metadata.create_all(self._engine)

    @staticmethod
    def _enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    def save(self, snapshot: PurchaseSessionSnapshot) -> None:
        self._write(snapshot, create_only=False)

    def create(self, snapshot: PurchaseSessionSnapshot) -> None:
        self._write(snapshot, create_only=True)

    def _write(
        self,
        snapshot: PurchaseSessionSnapshot,
        *,
        create_only: bool,
    ) -> None:
        now = datetime.now(UTC)
        with self._session_factory.begin() as session:
            record = session.get(PurchaseSessionRecord, snapshot.task_id)
            if record is not None and create_only:
                raise PurchaseSessionAlreadyExists(
                    f"Purchase session already exists: {snapshot.task_id}"
                )
            if record is not None and record.user_id != snapshot.user_id:
                raise PurchaseSessionOwnershipConflict(
                    f"Purchase session ownership conflict: {snapshot.task_id}"
                )
            if record is None:
                record = PurchaseSessionRecord(
                    task_id=snapshot.task_id,
                    user_id=snapshot.user_id,
                    state=snapshot.state_machine.state.value,
                    store_id=(snapshot.cart.store_id if snapshot.cart else None),
                    cart_version=snapshot.state_machine.cart_version,
                    confirmation_id=snapshot.state_machine.confirmation_id,
                    confirmed_cart_version=(
                        snapshot.state_machine.confirmed_cart_version
                    ),
                    context_json=snapshot.context.model_dump_json(),
                    applied_operation_ids_json=self._dump_operation_ids(snapshot),
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.state = snapshot.state_machine.state.value
                record.store_id = snapshot.cart.store_id if snapshot.cart else None
                record.cart_version = snapshot.state_machine.cart_version
                record.confirmation_id = snapshot.state_machine.confirmation_id
                record.confirmed_cart_version = (
                    snapshot.state_machine.confirmed_cart_version
                )
                record.context_json = snapshot.context.model_dump_json()
                record.applied_operation_ids_json = self._dump_operation_ids(snapshot)
                record.updated_at = now

            session.execute(
                delete(AssistantCartItemRecord).where(
                    AssistantCartItemRecord.task_id == snapshot.task_id
                )
            )
            session.flush()
            cart_items = snapshot.cart.items if snapshot.cart is not None else ()
            session.add_all(
                self._item_record(snapshot.task_id, item) for item in cart_items
            )

    def load(self, *, task_id: str, user_id: str) -> PurchaseSessionSnapshot:
        with self._session_factory() as session:
            record = session.scalar(
                select(PurchaseSessionRecord).where(
                    PurchaseSessionRecord.task_id == task_id,
                    PurchaseSessionRecord.user_id == user_id,
                )
            )
            if record is None:
                raise PurchaseSessionNotFound(
                    f"Purchase session was not found: {task_id}"
                )
            return self._snapshot(record)

    def load_latest_active(self, *, user_id: str) -> PurchaseSessionSnapshot | None:
        terminal_states = {
            PurchaseState.COMPLETED.value,
            PurchaseState.PARTIAL_FAILED.value,
            PurchaseState.FAILED.value,
            PurchaseState.CANCELLED.value,
        }
        with self._session_factory() as session:
            record = session.scalar(
                select(PurchaseSessionRecord)
                .where(
                    PurchaseSessionRecord.user_id == user_id,
                    PurchaseSessionRecord.state.not_in(terminal_states),
                )
                .order_by(PurchaseSessionRecord.updated_at.desc())
                .limit(1)
            )
            return self._snapshot(record) if record is not None else None

    def _snapshot(self, record: PurchaseSessionRecord) -> PurchaseSessionSnapshot:
        items = tuple(self._domain_item(item) for item in record.items)
        cart = (
            AssistantCart(
                store_id=record.store_id,
                version=record.cart_version,
                items=items,
                applied_operation_ids=tuple(
                    json.loads(record.applied_operation_ids_json)
                ),
            )
            if record.store_id is not None
            else None
        )
        state_machine = PurchaseStateMachine(
            state=PurchaseState(record.state),
            cart_version=record.cart_version,
            confirmation_id=record.confirmation_id,
            confirmed_cart_version=record.confirmed_cart_version,
        )
        return PurchaseSessionSnapshot(
            task_id=record.task_id,
            user_id=record.user_id,
            context=PurchaseSessionContext.model_validate_json(record.context_json),
            state_machine=state_machine,
            cart=cart,
        )

    def close(self) -> None:
        self._engine.dispose()

    @staticmethod
    def _dump_operation_ids(snapshot: PurchaseSessionSnapshot) -> str:
        return json.dumps(
            list(snapshot.cart.applied_operation_ids) if snapshot.cart else [],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _item_record(
        task_id: str, item: AssistantCartItem
    ) -> AssistantCartItemRecord:
        product = item.product
        return AssistantCartItemRecord(
            task_id=task_id,
            product_id=product.product_id,
            store_product_id=product.store_product_id,
            sku_id=product.sku_id,
            name=product.name,
            specification=product.specification,
            unit_price=product.unit_price,
            stock_available=product.stock_available,
            store_id=product.store_id,
            captured_at_iso=product.captured_at.isoformat(),
            source=product.source,
            quantity=item.quantity,
        )

    @staticmethod
    def _domain_item(record: AssistantCartItemRecord) -> AssistantCartItem:
        return AssistantCartItem(
            product=ProductSnapshot(
                product_id=record.product_id,
                store_product_id=record.store_product_id,
                sku_id=record.sku_id,
                name=record.name,
                specification=record.specification,
                unit_price=record.unit_price,
                stock_available=record.stock_available,
                store_id=record.store_id,
                captured_at=datetime.fromisoformat(record.captured_at_iso),
                source=record.source,
            ),
            quantity=record.quantity,
        )
