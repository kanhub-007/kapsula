# Implementation Guide — Consolidate Document Structure Building

> **Prerequisites:** Read the current `kapsula/presentation/shared/document_structure_builder.py` before starting.
> **Rollback:** `git checkout kapsula/presentation/api/routes/search.py kapsula/presentation/mcp/tools/search.py`

---

### Step 0: Verify the shared builder exists and works
**File:** `kapsula/presentation/shared/document_structure_builder.py`

Open the file and confirm it contains:
- `build_document_structure_from_subdocs(subdocs, db)` — takes list of ORM SubDocument objects
- `build_document_structure_from_document(document_id, fallback_name, db)` — for single-index docs
- `_fetch_hierarchy_cards(db, *, sub_document_id, document_id)` — internal helper
- `_cards_to_sections(cards)` — internal helper

**Critical — ORM object assumption:** The builder expects ORM `SubDocument` objects with `.breadcrumb_key`, `.id` attributes. If a call site fetches subdocs as dicts or raw query results, you must convert first. All 5 call sites in the current codebase use ORM objects, so this is fine.

**Critical — `doc.sub_documents` relationship:** In MCP tools `search.py`, subdocs are fetched via `db.query(SubDocument).filter(SubDocument.document_id == doc.id).all()`. In API `routes/search.py`, they use the ORM relationship `doc.sub_documents` or `routed_coll.documents`. Both return ORM objects — compatible with the shared builder. But verify: if `doc.sub_documents` is a lazy-loaded list that hasn't been loaded, you'll get a `DetachedInstanceError` outside a session. All 5 call sites are inside `db` session context, so this is fine.

**Verify: Run this command to check what's actually in the file:**
```bash
python -c "
import inspect
from kapsula.presentation.shared.document_structure_builder import (
    build_document_structure_from_subdocs,
    build_document_structure_from_document,
)
print(inspect.signature(build_document_structure_from_subdocs))
print(inspect.signature(build_document_structure_from_document))
"
```
Expected: `(subdocs: list[SubDocument], db: Session) -> list[dict]` and `(document_id: int, fallback_name: str, db: Session) -> list[dict]`

---

### Step 1: Add `limit` parameter to shared builder
**File:** `kapsula/presentation/shared/document_structure_builder.py`

One call site (`intelligent_search_document` route) originally used `limit(30)` for single-index documents while all others used `limit(20)`. Update `_fetch_hierarchy_cards` to accept a `limit` parameter so this difference is preserved:

```python
def _fetch_hierarchy_cards(db, *, sub_document_id=None, document_id=None, limit=20):
    ...
    return query.order_by(LibraryCard.level.desc()).limit(limit).all()
```

Then update `build_document_structure_from_document` to accept and pass a `limit` parameter (default 20). Callers that need 30 can pass `limit=30`.

**Verify:** `python -c "from kapsula.presentation.shared.document_structure_builder import build_document_structure_from_document; import inspect; print(inspect.signature(build_document_structure_from_document))"`

---

### Step 2: Migrate `routes/search.py` call sites
**File:** `kapsula/presentation/api/routes/search.py`

Three call sites to update:

**Site 1** — `intelligent_search_across_collections` (~line 363):
```python
# BEFORE (45 lines):
document_structure = []
routed_collection = db.query(Collection).filter(...).first()
if routed_collection:
    documents = db.query(Document).filter(...).all()
    for doc in documents:
        subdocs = db.query(SubDocument).filter(...).all()
        for subdoc in subdocs:
            hierarchy_cards = db.query(LibraryCard).filter(
                LibraryCard.sub_document_id == subdoc.id,
                LibraryCard.level.in_(["level_1", "level_2", "level_3"]),
            ).order_by(LibraryCard.level.desc()).limit(20).all()
            if hierarchy_cards:
                subdoc_structure = {"subdocument_name": subdoc.breadcrumb_key, "sections": []}
                for card in hierarchy_cards:
                    subdoc_structure["sections"].append({"level": card.level, "title": card.title})
                document_structure.append(subdoc_structure)

# AFTER (3 lines):
document_structure = []
for doc in documents:
    subdocs = db.query(SubDocument).filter(SubDocument.document_id == doc.id).all()
    document_structure.extend(build_document_structure_from_subdocs(subdocs, db))
```

**Site 2** — `intelligent_search_across_collections_streaming` (~line 721): Same pattern as Site 1.

**Site 3** — `intelligent_search_document` (~line 1106): Has both subdoc path and single-index fallback:
```python
# AFTER:
if subdocs:
    document_structure = build_document_structure_from_subdocs(subdocs, db)
else:
    document_structure = build_document_structure_from_document(
        document_id=document.id,
        fallback_name=document.filename,
        db=db,
    )
```

**Verify:** `python -m pytest tests/test_mcp/test_integration.py -k search`
**Common mistake:** Site 3 previously used `limit(30)` for single-index documents. Update the shared builder or pass the limit.

---

### Step 3: Migrate `mcp/tools/search.py` call sites
**File:** `kapsula/presentation/mcp/tools/search.py`

Two call sites to update:

**Site 4** — `_run_intelligent_collection_search` (~line 130):
The `_db_work` inner function builds structure inline. Replace with:
```python
document_structure = []
if routed_coll:
    for doc in routed_coll.documents:
        document_structure.extend(
            build_document_structure_from_subdocs(doc.sub_documents, db)
        )
```

**Site 5** — `intelligent_search_document` (~line 660): Same dual-path pattern:
```python
if subdocs:
    document_structure = build_document_structure_from_subdocs(subdocs, db)
else:
    document_structure = build_document_structure_from_document(
        document_id=doc.id, fallback_name=doc.filename, db=db,
    )
```

**Verify:** `python -m pytest tests/test_mcp/ -k search`

---

### Step 4: Remove unused imports
After migration, remove unused imports from both files:
- `from kapsula.infrastructure.data import LibraryCard, SubDocument` (if no longer directly used)
- Keep if used elsewhere in the file

**Verify:** `python -m ruff check kapsula/presentation/api/routes/search.py kapsula/presentation/mcp/tools/search.py`
**Common mistake:** `LibraryCard` and `SubDocument` may still be used for other queries (citation extraction, sub-document resolution). Only remove if truly unused.

---

### Step 5: Add `limit` parameter to shared builder
**File:** `kapsula/presentation/shared/document_structure_builder.py`

Update `_fetch_hierarchy_cards` to accept `limit: int = 20`:
```python
def _fetch_hierarchy_cards(db, *, sub_document_id=None, document_id=None, limit=20):
    ...
    return query.order_by(LibraryCard.level.desc()).limit(limit).all()
```

Then `build_document_structure_from_document` can pass `limit=30` for single-index documents if the old behaviour required it.

**Verify:** `python -c "from kapsula.presentation.shared.document_structure_builder import *; print('OK')"`
