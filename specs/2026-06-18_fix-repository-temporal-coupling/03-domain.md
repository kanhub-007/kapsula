# Domain Model — Fix Repository Temporal Coupling

## Modified Interfaces

### AccountRepository.save
`core/domain/interfaces/account_repository.py`
```python
# BEFORE:
@abstractmethod
def save(self, db: Any, account: Account) -> None: ...

# AFTER:
@abstractmethod
def save(self, db: Any, account: Account) -> Account:
    """Persist a new account and return it with the generated identity."""
```

### CollectionRepository.save
`core/domain/interfaces/collection_repository.py`
```python
# BEFORE:
@abstractmethod
def save(self, db: Any, collection: Collection) -> None: ...

# AFTER:
@abstractmethod
def save(self, db: Any, collection: Collection) -> Collection:
    """Persist a new collection and return it with the generated identity."""
```

### DocumentRepository.save_document
`core/domain/interfaces/document_repository.py`
```python
# BEFORE:
@abstractmethod
def save_document(self, db: Any, document: Document) -> None: ...

# AFTER:
@abstractmethod
def save_document(self, db: Any, document: Document) -> Document:
    """Persist a new domain Document and return it with the generated identity."""
```

## Modified Infrastructure Implementations

### SqlDocumentRepository.save_document
`infrastructure/repositories/data/sql_document_repository.py`
- Uses `dataclasses.replace(document, id=orm_doc.id)` instead of mutating `document.id = orm_doc.id`
- Returns the new copy

### SqlAccountRepository.save
`infrastructure/repositories/data/sql_account_repository.py`
- Uses `dataclasses.replace(account, id=orm_account.id, created_at=orm_account.created_at)`
- Returns the new copy

### SqlCollectionRepository.save
`infrastructure/repositories/data/sql_collection_repository.py`
- Uses `dataclasses.replace(collection, id=orm_collection.id, created_at=orm_collection.created_at)`
- Returns the new copy

### SqlSearchDataAccess.save_account
`infrastructure/repositories/data/sql_search_data_access.py`
- Adds `self._db.refresh(account)` and `return account`
- Return type becomes `Account` (was implicit `None`)

## Modified Application Use Cases

### UploadDocumentUseCase.execute
`core/application/use_cases/upload_document.py`
```python
# BEFORE (relies on mutation):
self._document_repository.save_document(db, doc)

# AFTER (uses return value):
doc = self._document_repository.save_document(db, doc)
```

## Callers That Must Be Updated

| Caller | File | Change |
|--------|------|--------|
| `UploadDocumentUseCase.execute()` | `upload_document.py` | `doc = repo.save_document(db, doc)` |
| `POST /accounts` route | `routes/accounts.py` | `acc = _account_repo.save(db, acc)` |
| `POST /collections` route | `routes/collections.py` | `collection = _collection_repo.save(db, collection)` |

## Why `dataclasses.replace` Not `copy.deepcopy`

Domain entities like `Document` have `field(default_factory=list)` for `chunks` and `sub_documents`. `replace()` creates a shallow copy where these list references are shared. This is safe because:
1. We only replace scalar fields (`id`, `created_at`)
2. The `chunks`/`sub_documents` lists are empty `[]` at save time (populated later from DB reads)
3. Callers treat domain entities as value objects after construction
