# Scenarios — Consolidate Document Structure Building

---

### Scenario: API route uses shared builder (collections path)
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given `intelligent_search_across_collections` route currently builds document_structure inline (~45 lines)
  When  the route is updated to call `build_document_structure_from_subdocs(subdocs, db)`
  Then  the route code is reduced to a single function call
  And   the returned document_structure has identical format

**Verify:**
```python
# Before (inline):
document_structure = []
for subdoc in subdocs:
    cards = db.query(LibraryCard).filter(...).all()
    if cards:
        document_structure.append({...})
        
# After (shared):
from kapsula.presentation.shared.document_structure_builder import (
    build_document_structure_from_subdocs,
)
document_structure = build_document_structure_from_subdocs(subdocs, db)

# Assert structures are identical for the same inputs
```

---

### Scenario: All 5 call sites use the shared builder
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given 5 call sites currently build document_structure inline
  When  migration is complete
  Then  no call site contains `db.query(LibraryCard).filter(LibraryCard.level.in_([...]))`
  And   all 5 import from `kapsula.presentation.shared.document_structure_builder`

**Verify:**
```bash
grep -rn "LibraryCard.level.in_" kapsula/presentation/api/routes/search.py
# Should return 0 matches

grep -rn "LibraryCard.level.in_" kapsula/presentation/mcp/tools/search.py
# Should return 0 matches

grep -rn "build_document_structure" kapsula/presentation/api/routes/search.py
# Should return 2 matches (one for subdocs path, one for single-index path)

grep -rn "build_document_structure" kapsula/presentation/mcp/tools/search.py
# Should return 1 match (for subdocs path)
```

---

### Scenario: Single-index document path works correctly
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a document without sub-documents (single FAISS index)
  When  `build_document_structure_from_document(document_id, fallback_name, db)` is called
  Then  it returns structure using the document's own library cards

**Verify:**
```python
structure = build_document_structure_from_document(
    document_id=doc.id,
    fallback_name=doc.filename,
    db=db,
)
assert len(structure) <= 1
if structure:
    assert structure[0]["subdocument_name"] == doc.filename
    assert all("level" in s and "title" in s for s in structure[0]["sections"])
```

---

### Scenario: Existing search responses are unchanged
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given an intelligent search request with enable_planning=True
  When  the route uses the shared structure builder
  Then  the SearchPlan in the response has the same strategy and queries as before

**Verify:**
Run `intelligent_search` on a known document with planning enabled before and after the refactoring. Compare the `plan.strategy` and `plan.queries` fields — they should be identical (assuming deterministic LLM temperature=0.3).
