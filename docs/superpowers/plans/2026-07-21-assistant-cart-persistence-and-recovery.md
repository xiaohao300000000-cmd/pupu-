# Assistant Cart Persistence and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Every production change follows superpowers:test-driven-development.

**Goal:** Persist each user's purchase task, short-term task context, state machine, and assistant cart in SQLite so an interrupted process can resume without losing or mixing user data.

**Architecture:** Add a small SQLAlchemy-backed repository beneath the existing domain objects. A `PurchaseSessionSnapshot` is the persistence boundary: it contains the task/user identity, resumable context, `PurchaseStateMachine`, and immutable `AssistantCart`. Saving replaces the session and its cart items in one transaction; loading always requires both `task_id` and `user_id` so one account cannot read another account's state.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2, SQLite, pytest, Ruff.

---

## Scope and acceptance gates

- This plan does not implement or inspect `seal/sign`, APKs, native code, protected Pupu endpoints, or credentials.
- This plan does not add CLI commands, Feishu integration, product search, order history, or real-cart writes.
- Assistant-cart products remain facts sourced from `source="pupu"`; persistence must not invent products, prices, or stock.
- A save must atomically persist task state, resumable context, cart version, operation IDs, and all cart items.
- A repository recreated against the same SQLite file must recover an equal domain snapshot.
- Loading requires `task_id + user_id`; a different user receives `PurchaseSessionNotFound`, not another user's data.
- Updating an existing task replaces old cart items without duplicates.
- No Token, phone number, address, or Pupu credential field is introduced into this storage schema.

## File map

- Modify `pyproject.toml`: add SQLAlchemy runtime dependency.
- Modify `.env.example`: add the ignored local SQLite path.
- Modify `src/pupu_assistant/config.py`: expose `pupu_database_path`.
- Create `src/pupu_assistant/domain/purchase/__init__.py`: purchase-domain package boundary.
- Create `src/pupu_assistant/domain/purchase/session.py`: resumable context and snapshot types.
- Create `src/pupu_assistant/storage/purchase_session_repository.py`: SQLAlchemy tables and repository.
- Create `tests/domain/test_purchase_session.py`: domain validation tests.
- Create `tests/storage/test_purchase_session_repository.py`: persistence, restart, update, and isolation tests.
- Modify `tests/test_config.py`: database-path configuration tests.
- Modify `README.md`: accurate persistence status and boundary.
- Modify `HANDOFF.md`: verification evidence and next document-defined step.

## Task 1: Add the SQLite configuration boundary

**Files:**

- Modify: `pyproject.toml`
- Modify: `.env.example`
- Modify: `src/pupu_assistant/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing configuration assertions**

Add these assertions to `test_settings_use_safe_non_secret_defaults`:

```python
assert settings.pupu_database_path == Path(".local/pupu-assistant.db")
```

Add `PUPU_DATABASE_PATH` to the environment variables removed at the start of the test. In `test_settings_allow_environment_override`, set and assert:

```python
monkeypatch.setenv("PUPU_DATABASE_PATH", "/tmp/pupu-test.db")
assert settings.pupu_database_path == Path("/tmp/pupu-test.db")
```

- [ ] **Step 2: Run the targeted test and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_config.py -q
```

Expected: FAIL because `Settings` has no `pupu_database_path`.

- [ ] **Step 3: Add the minimal configuration and dependency**

Add to `Settings`:

```python
pupu_database_path: Path = Path(".local/pupu-assistant.db")
```

Add to `.env.example`:

```text
PUPU_DATABASE_PATH=.local/pupu-assistant.db
```

Add to runtime dependencies in `pyproject.toml`:

```text
sqlalchemy>=2.0,<3
```

- [ ] **Step 4: Install the editable package and verify GREEN**

Run:

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest tests/test_config.py -q
```

Expected: all configuration tests PASS.

- [ ] **Step 5: Commit the configuration boundary**

```bash
git add pyproject.toml .env.example src/pupu_assistant/config.py tests/test_config.py
git commit -m "Add assistant persistence configuration"
```

## Task 2: Define the resumable purchase-session domain snapshot

**Files:**

- Create: `src/pupu_assistant/domain/purchase/__init__.py`
- Create: `src/pupu_assistant/domain/purchase/session.py`
- Create: `tests/domain/test_purchase_session.py`

- [ ] **Step 1: Write the failing domain tests**

Create tests that construct a cart and state machine, then assert the snapshot preserves task ownership and context:

```python
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from pupu_assistant.application.state_machine import PurchaseState, PurchaseStateMachine
from pupu_assistant.domain.assistant_cart.models import ProductSnapshot
from pupu_assistant.domain.assistant_cart.service import AssistantCart
from pupu_assistant.domain.purchase.session import (
    PurchaseSessionContext,
    PurchaseSessionSnapshot,
)


def test_purchase_session_snapshot_keeps_resumable_context() -> None:
    product = ProductSnapshot(
        product_id="milk-1",
        sku_id="sku-milk-1",
        name="Fresh Milk",
        specification="950 ml",
        unit_price=Decimal("12.50"),
        stock_available=True,
        store_id="store-1",
        captured_at=datetime(2026, 7, 21, tzinfo=UTC),
        source="pupu",
    )
    cart = AssistantCart(store_id="store-1").add(
        product, quantity=1, operation_id="add-milk"
    )
    machine = PurchaseStateMachine(
        state=PurchaseState.AWAITING_CLARIFICATION,
        cart_version=cart.version,
    )
    context = PurchaseSessionContext(
        original_request="帮我买牛奶",
        pending_question="这次想要鲜奶还是常温奶？",
        servings=None,
        budget=Decimal("20.00"),
    )

    snapshot = PurchaseSessionSnapshot(
        task_id="task-1",
        user_id="user-1",
        context=context,
        state_machine=machine,
        cart=cart,
    )

    assert snapshot.context.pending_question == "这次想要鲜奶还是常温奶？"
    assert snapshot.cart.version == snapshot.state_machine.cart_version


def test_purchase_session_rejects_cart_state_version_mismatch() -> None:
    with pytest.raises(ValidationError, match="cart version"):
        PurchaseSessionSnapshot(
            task_id="task-1",
            user_id="user-1",
            context=PurchaseSessionContext(original_request="买牛奶"),
            state_machine=PurchaseStateMachine(cart_version=1),
            cart=AssistantCart(store_id="store-1", version=0),
        )
```

- [ ] **Step 2: Run the targeted test and verify RED**

Run:

```bash
.venv/bin/pytest tests/domain/test_purchase_session.py -q
```

Expected: collection FAIL because the purchase-session module does not exist.

- [ ] **Step 3: Implement the minimal frozen domain models**

Create:

```python
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pupu_assistant.application.state_machine import PurchaseStateMachine
from pupu_assistant.domain.assistant_cart.service import AssistantCart


class PurchaseSessionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    original_request: str = Field(min_length=1)
    pending_question: str | None = None
    dish_name: str | None = None
    servings: int | None = Field(default=None, ge=1)
    budget: Decimal | None = Field(default=None, ge=0)
    last_card_action_id: str | None = None


class PurchaseSessionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    task_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    context: PurchaseSessionContext
    state_machine: PurchaseStateMachine
    cart: AssistantCart

    @model_validator(mode="after")
    def require_matching_cart_version(self) -> "PurchaseSessionSnapshot":
        if self.state_machine.cart_version != self.cart.version:
            raise ValueError("state machine cart version must match cart version")
        return self
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/pytest tests/domain/test_purchase_session.py -q
```

Expected: both tests PASS.

- [ ] **Step 5: Commit the domain boundary**

```bash
git add src/pupu_assistant/domain/purchase tests/domain/test_purchase_session.py
git commit -m "Define resumable purchase session"
```

## Task 3: Persist and recover sessions atomically with SQLAlchemy

**Files:**

- Create: `src/pupu_assistant/storage/purchase_session_repository.py`
- Create: `tests/storage/test_purchase_session_repository.py`

- [ ] **Step 1: Write a failing round-trip and restart test**

The test must:

1. Create a file-backed temporary SQLite database.
2. Save a snapshot containing one product, one operation ID, a pending question, and an awaiting-clarification state.
3. Close the repository.
4. Create a new repository instance against the same file.
5. Load with the same `task_id + user_id` and assert domain equality.

Use this public API:

```python
repository = SqlAlchemyPurchaseSessionRepository(tmp_path / "assistant.db")
repository.save(snapshot)
repository.close()

reopened = SqlAlchemyPurchaseSessionRepository(tmp_path / "assistant.db")
assert reopened.load(task_id="task-1", user_id="user-1") == snapshot
reopened.close()
```

- [ ] **Step 2: Run the restart test and verify RED**

Run:

```bash
.venv/bin/pytest tests/storage/test_purchase_session_repository.py::test_session_survives_repository_restart -q
```

Expected: collection FAIL because the repository does not exist.

- [ ] **Step 3: Implement the SQLAlchemy schema and mapping**

Create two SQLAlchemy ORM tables:

```text
purchase_sessions
  task_id primary key
  user_id indexed, not null
  state, not null
  store_id, not null
  cart_version, not null
  confirmation_id, nullable
  confirmed_cart_version, nullable
  context_json, not null
  applied_operation_ids_json, not null
  created_at, not null
  updated_at, not null

assistant_cart_items
  task_id foreign key purchase_sessions.task_id on delete cascade
  product_id
  sku_id
  name
  specification
  unit_price as Numeric(18, 4)
  stock_available
  store_id
  captured_at
  source
  quantity
  primary key task_id + product_id
```

Repository rules:

- create the parent directory unless the path is `:memory:`;
- enable SQLite foreign keys on connection;
- call `Base.metadata.create_all()` at construction;
- serialize context with `model_dump_json()`;
- serialize operation IDs with `json.dumps(list(...), ensure_ascii=False)`;
- within one `Session.begin()`, upsert the session row, delete its prior item rows, and insert the current items;
- reconstruct `ProductSnapshot`, `AssistantCartItem`, `AssistantCart`, `PurchaseStateMachine`, and `PurchaseSessionSnapshot` on load;
- expose `close()` to dispose the engine.

- [ ] **Step 4: Run the restart test and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/storage/test_purchase_session_repository.py::test_session_survives_repository_restart -q
```

Expected: PASS.

- [ ] **Step 5: Commit the first repository slice**

```bash
git add src/pupu_assistant/storage/purchase_session_repository.py tests/storage/test_purchase_session_repository.py
git commit -m "Persist purchase sessions in SQLite"
```

## Task 4: Prove user isolation and idempotent replacement

**Files:**

- Modify: `src/pupu_assistant/storage/purchase_session_repository.py`
- Modify: `tests/storage/test_purchase_session_repository.py`

- [ ] **Step 1: Write the failing user-isolation test**

Add:

```python
def test_load_does_not_cross_user_boundary(repository, snapshot) -> None:
    repository.save(snapshot)

    with pytest.raises(PurchaseSessionNotFound):
        repository.load(task_id=snapshot.task_id, user_id="different-user")
```

The exception message must not reveal the actual owner ID.

- [ ] **Step 2: Write the failing replacement test**

Save version 1 of a cart, then save version 2 after replacing its only product. Assert loading returns only the replacement, the newest version, and both applied operation IDs. Also query the item table in the test and assert it contains exactly one row for the task.

- [ ] **Step 3: Run both tests and verify RED**

Run:

```bash
.venv/bin/pytest \
  tests/storage/test_purchase_session_repository.py::test_load_does_not_cross_user_boundary \
  tests/storage/test_purchase_session_repository.py::test_save_replaces_old_cart_items_atomically \
  -q
```

Expected: FAIL until ownership filtering and replacement behavior are complete.

- [ ] **Step 4: Implement minimal ownership and replacement behavior**

`load()` must select using both columns:

```python
select(PurchaseSessionRecord).where(
    PurchaseSessionRecord.task_id == task_id,
    PurchaseSessionRecord.user_id == user_id,
)
```

If no row is found, raise:

```python
PurchaseSessionNotFound(f"Purchase session was not found: {task_id}")
```

Do not include an owner ID or serialized context in the exception.

- [ ] **Step 5: Verify targeted and full repository GREEN**

Run:

```bash
.venv/bin/pytest tests/storage/test_purchase_session_repository.py -q
```

Expected: all persistence tests PASS.

- [ ] **Step 6: Commit recovery hardening**

```bash
git add src/pupu_assistant/storage/purchase_session_repository.py tests/storage/test_purchase_session_repository.py
git commit -m "Enforce purchase session recovery boundaries"
```

## Task 5: Document the exact completed boundary and verify the repository

**Files:**

- Modify: `README.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Update README without overstating live capability**

Document:

- assistant cart and purchase task state are persisted in local ignored SQLite;
- process restart recovery is covered by an automated file-backed test;
- session loading is scoped by `task_id + user_id`;
- no Pupu credential, protected request, live product result, or real cart result is stored or claimed by this slice;
- `PUPU_DATABASE_PATH` defaults to `.local/pupu-assistant.db`.

- [ ] **Step 2: Update HANDOFF status and next step**

Record the exact test counts from the fresh final run. Keep the document-defined sequence explicit:

1. protected Connector validation remains blocked on the user-owned signer/vector work;
2. assistant-cart persistence/restart recovery is complete after this slice;
3. the next non-reverse milestone is application orchestration for the minimal “帮我买牛奶” flow using only verified Connector results;
4. Feishu, batch purchase, repurchase, and recipe flows remain later stages.

- [ ] **Step 3: Run complete fresh verification**

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests scripts
git diff --check origin/codex/seal-sign-static-followup...HEAD
```

Expected: all tests PASS, Ruff reports `All checks passed!`, and `git diff --check` exits 0.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md HANDOFF.md
git commit -m "Document assistant session recovery"
```

- [ ] **Step 5: Inspect the final branch scope**

Run:

```bash
git status --short --branch
git log --oneline origin/codex/seal-sign-static-followup..HEAD
git diff --stat origin/codex/seal-sign-static-followup...HEAD
```

Expected: clean worktree and changes limited to persistence configuration, purchase-session domain/storage, tests, README, HANDOFF, and this plan.
