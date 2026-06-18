# Fix Repository Temporal Coupling — Return Copy Instead of Mutating Input

## User Story
As a developer using `SqlDocumentRepository.save_document()`, I want the method to return the persisted entity (with its generated ID) instead of silently mutating the input domain entity, so that the mutation side-effect is explicit and the domain entity remains immutable after construction.

## Context

`SqlDocumentRepository.save_document()` currently mutates the input domain entity:
```python
def save_document(self, db: Session, document: DomainDocument) -> None:
    orm_doc = document_to_orm(document)
    db.add(orm_doc)
    db.commit()
    db.refresh(orm_doc)
    # Push back generated ID — MUTATES input
    document.id = orm_doc.id
```

This is a pragmatic pattern for SQLAlchemy identity push-back, but it:
- Violates the expectation that domain entities are value-like after construction
- Makes the mutation invisible to the caller (no return value, just a side effect)
- Creates temporal coupling: caller must know to read `document.id` after the call
- Is inconsistent with `save_account` in `SqlSearchDataAccess` which doesn't push back

## Non-Goals
- Changing the domain entity from dataclass to frozen (too broad)
- Introducing a Result monad or Either type
- Changing repository method signatures beyond `save*` methods
- Affecting non-repository code that mutates domain entities intentionally

## Architecture Decision

**Option A: Return a copy with the ID populated**
```python
def save_document(self, db: Session, document: DomainDocument) -> DomainDocument:
    orm_doc = document_to_orm(document)
    db.add(orm_doc)
    db.commit()
    db.refresh(orm_doc)
    return replace(document, id=orm_doc.id)
```
Pro: Explicit, pure. Con: All callers must use the return value.

**Option B: Accept mutable ID as a separate out-parameter pattern**
```python
def save_document(self, db: Session, document: DomainDocument) -> int:
    ...
    return orm_doc.id
```
Pro: No mutation. Con: Caller must manually set `document.id = returned_id`.

**Decision: Option A** — return a new domain entity with populated ID. This is the most idiomatic Python approach (similar to `dataclasses.replace`), keeps the original entity unmodified, and makes the side effect explicit in the return type.

Backward compatibility: Since `save_document` currently returns `None`, changing to return `DomainDocument` is a signature change but not a breaking one — callers that ignore the return value still work (the old entity just won't have `id` set). Callers that need the ID must use the return value.
