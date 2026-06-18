# Scenarios — Fix Repository Temporal Coupling

---

### Scenario: save_document returns a new entity with populated ID
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a new DomainDocument with id=None is passed to save_document
  When  save_document is called
  Then  the return value is a DomainDocument with id set to the DB-generated value
  And   the original input document still has id=None

**Input table:**
| Field      | Type           | Example    | Constraints       |
|------------|----------------|------------|-------------------|
| document   | DomainDocument | id=None, job_id="abc" | Valid domain entity |
| db         | Session        | SQLAlchemy session | Open session    |

**Expected output:**
| Assertion                              | How to verify                      |
|----------------------------------------|------------------------------------|
| returned.id is not None                | isinstance(returned.id, int)       |
| returned.id == original.id in DB       | Query DB for job_id                |
| input_document.id is still None        | Assert no mutation on input        |
| returned.job_id == input.job_id        | All other fields preserved         |

**Verify (Classical school, black-box):**
```python
fake_db = InMemorySession()
repo = SqlDocumentRepository()

original = DomainDocument(job_id="test-123", filename="test.md", ...)
result = repo.save_document(fake_db, original)

assert result.id is not None  # populated
assert original.id is None    # NOT mutated
assert result.job_id == "test-123"
assert result.filename == "test.md"
```

**Also test:**
- Save with id already set (update case) → should still work, return same entity
- Save with minimal required fields → returns entity with defaults

---

### Scenario: UploadDocumentUseCase uses the returned entity
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given UploadDocumentUseCase calls document_repository.save_document()
  When  the document is persisted
  Then  the use case uses the returned entity (with populated id) for subsequent operations

**Verify:**
```python
# Before (relies on mutation):
self._document_repository.save_document(db, doc)
# doc.id is now populated via mutation

# After (uses return value):
doc = self._document_repository.save_document(db, doc)
# doc.id is populated on the RETURNED entity
```

---

### Scenario: DeleteDocumentUseCase is unaffected
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given DeleteDocumentUseCase never calls save_document (it calls find/mark_archived/cascade_delete)
  When  save_document signature changes
  Then  DeleteDocumentUseCase compiles and works without changes

**Verify:**
```python
# DeleteDocumentUseCase should still compile and pass tests
from kapsula.core.application.use_cases.delete_document import DeleteDocumentUseCase
# No import errors
```

---

### Scenario: All repository save methods are consistent
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given `AccountRepository.save()`, `CollectionRepository.save()`, and `DocumentRepository.save_document()` exist
  When  any save method is called
  Then  all three follow the same pattern: return the persisted entity

**Verify:**
```python
# AccountRepository.save
account = repo.save(db, account)  # returns Account with populated id
assert account.id is not None

# CollectionRepository.save
collection = repo.save(db, collection)  # returns Collection with populated id
assert collection.id is not None

# DocumentRepository.save_document
document = repo.save_document(db, document)  # returns Document with populated id
assert document.id is not None
```

---

### Scenario: Existing MCP tools that call save_account still compile
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given `SqlSearchDataAccess.save_account()` currently has no return value
  When  it is updated to return the account
  Then  callers that ignore the return value still work
  And   callers that need the ID use the return value

**Verify:**
```python
# Old caller (ignores return):
repo.save_account(account)  # still works, return value is ignored

# New caller (uses return):
account = repo.save_account(account)  # explicit
```
