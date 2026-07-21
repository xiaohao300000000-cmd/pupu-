from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, String, create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from pupu_assistant.storage.purchase_session_repository import Base


class ProcessedEventRecord(Base):
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class SqlAlchemyEventDedupRepository:
    """Claims event IDs once so duplicate Feishu delivery is idempotent."""

    def __init__(self, database_path: Path | str) -> None:
        path = Path(database_path)
        if path == Path(":memory:"):
            database_url = "sqlite+pysqlite:///:memory:"
        else:
            resolved = path.expanduser().resolve()
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

    def claim(self, *, event_id: str, event_type: str, user_id: str) -> bool:
        try:
            with self._session_factory.begin() as session:
                session.add(
                    ProcessedEventRecord(
                        event_id=event_id,
                        event_type=event_type,
                        user_id=user_id,
                        processed_at=datetime.now(UTC),
                    )
                )
            return True
        except IntegrityError:
            return False

    def close(self) -> None:
        self._engine.dispose()
