# Implementation Guide — Fix Repository Temporal Coupling

> **This spec MUST be done FIRST** (before Spec 2 — wire-upload-usecase). Spec 2's `UploadDocumentUseCase` calls `save_document` and must capture the return value.
> **Rollback:** `git checkout kapsula/core/domain/interfaces/account_repository.py kapsula/core/domain/interfaces/collection_repository.py kapsula/core/domain/interfaces/document_repository.py kapsula/infrastructure/repositories/data/sql_document_repository.py kapsula/infrastructure/repositories/data/sql_account_repository.py kapsula/infrastructure/repositories/data/sql_collection_repository.py kapsula/infrastructure/repositories/data/sql_search_data_access.py`

---

## Important: `dataclasses.replace` and Mutable Defaults

Domain entities like `Document` have mutable default fields:
```python
@dataclass
class Document:
    chunks: list["Chunk"] = field(default_factory=list)
    sub_documents: list["SubDocument"] = field(default_factory=list)
```

`dataclasses.replace(document, id=123)` creates a SHALLOW copy. The `chunks` and `sub_documents` lists are shared references between the original and the copy. This is fine for our use case because:
1. We only replace `id` (an int) and `created_at` (a datetime)
2. The returned entity's `chunks`/`sub_documents` lists are the same empty `[]` as the input
3. Callers never mutate these lists after construction

If you need a deep copy, use `copy.deepcopy()` instead. But for now, `replace()` is sufficient.

---

### Step 1: Update Repository Interface Signatures
**Files:** 
- `kapsula/core/domain/interfaces/account_repository.py`
- `kapsula/core/domain/interfaces/collection_repository.py`
- `kapsula/core/domain/interfaces/document_repository.py`

Change return types from `None` to the domain entity:

```python
# account_repository.py
@abstractmethod
def save(self, db: Any, account: Account) -> Account:
    """Persist a new account and return it with the generated identity."""

# collection_repository.py
@abstractmethod
def save(self, db: Any, collection: Collection) -> Collection:
    """Persist a new collection and return it with the generated identity."""

# document_repository.py
@abstractmethod
def save_document(self, db: Any, document: Document) -> Document:
    """Persist a new domain Document and return it with the generated identity."""
```

**Verify:** `python -m ruff check kapsula/core/domain/interfaces/`

---

### Step 2: Update SQL Implementations
**File:** `kapsula/infrastructure/repositories/data/sql_document_repository.py`

Add `from dataclasses import replace` at the top, then update `save_document`:

```python
from dataclasses import replace
# ... existing imports ...

def save_document(self, db: Session, document: DomainDocument) -> DomainDocument:
    orm_doc = document_to_orm(document)
    db.add(orm_doc)
    db.commit()
    db.refresh(orm_doc)
    return replace(document, id=orm_doc.id)
```

Remove the old mutation line `document.id = orm_doc.id`.

**File:** `kapsula/infrastructure/repositories/data/sql_account_repository.py`

```python
def save(self, db: Session, account: Account) -> Account:
    orm_account = account_to_orm(account)
    db.add(orm_account)
    db.commit()
    db.refresh(orm_account)
    return replace(account, id=orm_account.id, created_at=orm_account.created_at)
```

**File:** `kapsula/infrastructure/repositories/data/sql_collection_repository.py`

```python
def save(self, db: Session, collection: Collection) -> Collection:
    orm_collection = collection_to_orm(collection)
    db.add(orm_collection)
    db.commit()
    db.refresh(orm_collection)
    return replace(collection, id=orm_collection.id, created_at=orm_collection.created_at)
```

**Verify:** `python -m ruff check kapsula/infrastructure/repositories/data/`

---

### Step 3: Update UploadDocumentUseCase
**File:** `kapsula/core/application/use_cases/upload_document.py`

```python
# Before:
self._document_repository.save_document(db, doc)
# doc.id is silently mutated here

# After:
doc = self._document_repository.save_document(db, doc)
# doc now refers to the returned entity with populated id
```

The `doc` variable is used after save for progress tracking (but only uses `job_id`, `filename`, `collection_name` — none depend on `id`). Still, use the return value for correctness.

**Verify:** `python -m pytest tests/ -k upload`

---

### Step 4: Update Other Callers of save_document/save
Search for all callers:
```bash
grep -rn "save_document\|\.save(" kapsula/ --include="*.py" | grep -v test | grep -v __pycache__
```

Update each caller to use the return value:
- `presentation/api/routes/documents.py` — if still using direct ORM (pre-wiring spec)
- `presentation/api/routes/accounts.py` — `_account_repo.save(db, acc)` → capture return
- `presentation/api/routes/collections.py` — `_collection_repo.save(db, collection)` → capture return

**Verify:** `python -m pytest tests/test_mcp/test_integration.py`

---

### Step 5: Update SqlSearchDataAccess.save_account
**File:** `kapsula/infrastructure/repositories/data/sql_search_data_access.py`

**First, verify the current implementation.** Run:
```bash
grep -A5 "def save_account" kapsula/infrastructure/repositories/data/sql_search_data_access.py
```

Currently it looks like:
```python
def save_account(self, account) -> None:
    self._db.add(account)
    self._db.commit()
```

This method already mutates `account` (SQLAlchemy sets `account.id` after `commit()`). It just doesn't return it. Change to:
```python
def save_account(self, account) -> Account:
    """Persist an account and return it with the generated identity."""
    self._db.add(account)
    self._db.commit()
    self._db.refresh(account)
    return account
```

Note: Added `self._db.refresh(account)` — this ensures the returned object has all DB-generated fields (id, created_at). Without `refresh()`, the `account.id` may or may not be populated depending on SQLAlchemy configuration.

**Find all callers:**
```bash
grep -rn "save_account" kapsula/ --include="*.py" | grep -v __pycache__
```

Expected callers:
- `kapsula/presentation/api/routes/accounts.py` — `_account_repo.save(db, acc)` (uses AccountRepository, not SqlSearchDataAccess — no change needed)
- `kapsula/infrastructure/repositories/data/sql_search_data_access.py` — internal use
- Any test files — update to capture return value

**Verify:** `python -c "from kapsula.infrastructure.repositories.data.sql_search_data_access import SqlSearchDataAccess"`

---

### Step 6: Run Full Test Suite
```bash
pytest tests/ -v
```

**Common mistake:** Some test factories may create entities with `id=None` and rely on mutation to populate it. Update tests to use the return value.
