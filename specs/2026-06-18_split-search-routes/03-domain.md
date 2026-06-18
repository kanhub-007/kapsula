# Domain Model — Split Search Routes

## Modified Entities

None. This is a file-splitting refactoring with zero logic changes.

## Modified Interfaces

None. No domain interfaces are changed.

## New Presentation-Layer Helpers

### extract_citation_from_result (moved, not new)
Moved from `routes/search.py` to `routes/search_helpers.py`. Signature unchanged:
```python
def extract_citation_from_result(
    result: dict, db: Session, document_id: int = None
) -> Citation | None: ...
```

### run_search_documents_text (moved, not new)
Moved from `mcp/tools/search.py` to `mcp/tools/_search_helpers.py`. Signature unchanged:
```python
async def run_search_documents_text(
    query: str, top_k: int = 10, context_mode: str = "none",
    account_id: str | None = None, collection_id: str | None = None,
    node_type_filter: str | None = None, routing_mode: str = "auto",
) -> str: ...
```

### run_intelligent_collection_search (moved, not new)
Same pattern — moved from `search.py` to `_search_helpers.py`.

## Entity vs ORM Separation
All sub-modules use ORM models directly (CQRS-lite read exception). Imports needed per sub-module are documented in the implementation guide.

## Router Structure
```
presentation/api/routes/
├── search_collection.py     → router = APIRouter()
├── search_document.py       → router = APIRouter()
├── search_intelligent.py    → router = APIRouter()
├── search_helpers.py        → no router, just helper functions
└── __init__.py              → api_router includes all sub-routers under /search prefix
```
