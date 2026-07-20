from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from pupu_assistant.domain.cart_write import CONFIRMATION_PHRASE, CartPreview

if os.name == "nt":
    import msvcrt

    def _lock_file(handle: Any) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock_file(handle: Any) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock_file(handle: Any) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def _unlock_file(handle: Any) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ConfirmationError(RuntimeError):
    pass


class ConfirmationNotFound(ConfirmationError):
    pass


class ConfirmationUsed(ConfirmationError):
    pass


class ConfirmationExpired(ConfirmationError):
    pass


class ConfirmationPhraseMismatch(ConfirmationError):
    pass


class ConfirmationCorrupt(ConfirmationError):
    pass


class StoredConfirmation(BaseModel):
    model_config = ConfigDict(frozen=True)

    preview: CartPreview
    used_at: datetime | None = None

    @property
    def confirmation_id(self) -> str:
        return self.preview.confirmation_id


class ConfirmationStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")

    def put(self, preview: CartPreview) -> None:
        with self._exclusive_lock():
            records = self._read_records()
            records[preview.confirmation_id] = StoredConfirmation(preview=preview)
            self._write_records(records)

    def get(self, confirmation_id: str) -> StoredConfirmation:
        with self._exclusive_lock():
            record = self._read_records().get(confirmation_id)
            if record is None:
                raise ConfirmationNotFound("Confirmation does not exist")
            self._verify_integrity(record)
            return record

    def consume(
        self,
        confirmation_id: str,
        *,
        phrase: str,
        now: datetime,
    ) -> CartPreview:
        if phrase != CONFIRMATION_PHRASE:
            raise ConfirmationPhraseMismatch("Exact confirmation phrase is required")
        with self._exclusive_lock():
            records = self._read_records()
            record = records.get(confirmation_id)
            if record is None:
                raise ConfirmationNotFound("Confirmation does not exist")
            self._verify_integrity(record)
            if record.used_at is not None:
                raise ConfirmationUsed("Confirmation has already been used")
            if now >= record.preview.expires_at:
                raise ConfirmationExpired("Confirmation has expired")
            records[confirmation_id] = StoredConfirmation(
                preview=record.preview,
                used_at=now,
            )
            self._write_records(records)
            return record.preview

    @contextmanager
    def _exclusive_lock(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+") as lock_file:
            os.chmod(self._lock_path, 0o600)
            _lock_file(lock_file)
            try:
                yield
            finally:
                _unlock_file(lock_file)

    def _read_records(self) -> dict[str, StoredConfirmation]:
        if not self._path.exists():
            return {}
        raw: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
        return {
            confirmation_id: StoredConfirmation.model_validate(record)
            for confirmation_id, record in raw.items()
        }

    def _write_records(self, records: dict[str, StoredConfirmation]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                os.chmod(temporary_path, 0o600)
                json.dump(
                    {
                        key: record.model_dump(mode="json")
                        for key, record in records.items()
                    },
                    temporary,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._path)
            os.chmod(self._path, 0o600)
            temporary_path = None
        finally:
            if temporary_path is not None and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    @staticmethod
    def _verify_integrity(record: StoredConfirmation) -> None:
        if record.preview.preview_hash != record.preview.calculated_hash():
            raise ConfirmationCorrupt("Confirmation preview hash does not match")
