# Implementation Guide — Split Search Files

> **Prerequisites:** Spec 3 (consolidate-document-structure) should be done first so the shared builder is available.
> **Rollback:** `git checkout kapsula/presentation/api/routes/search.py kapsula/presentation/mcp/tools/search.py kapsula/presentation/api/routes/__init__.py kapsula/presentation/mcp/tools/__init__.py`

---

## ORM Imports Per Sub-Module

Each sub-module needs different ORM imports. Here's the full list so you know what to import in each new file:

| Sub-module | ORM imports needed |
|-----------|-------------------|
| `search_collection.py` | `Collection`, `Account`, `LibraryCard`, `Document`, `SubDocument` |
| `search_document.py` | `Document`, `SubDocument`, `Chunk`, `LibraryCard` |
| `search_intelligent.py` | `Collection`, `Account`, `LibraryCard`, `Document`, `SubDocument` |
| `search_helpers.py` | `Chunk` (for citation extraction) |
| `_search_helpers.py` (MCP) | `Collection`, `Account`, `LibraryCard`, `Document`, `SubDocument`, `SearchMissLog` |
| `search_documents.py` (MCP) | `Document`, `SubDocument` |
| `search_intelligent.py` (MCP) | `Document`, `SubDocument`, `LibraryCard` |
| `search_background.py` (MCP) | None (uses `_search_helpers`) |

---

## Route Ordering Warning

FastAPI matches routes in registration order. `POST /collections` MUST be registered before `POST /collections/{collection_id}`. Otherwise `"collections"` is captured as a `{collection_id}` parameter.

In `search_collection.py`, order the route definitions as:
1. `@router.post("/collections")` — `search_across_collections`
2. `@router.post("/collection")` — `search_collection_by_query_param` (alias)
3. `@router.post("/collections/{collection_id}")` — `search_collection`

In `routes/__init__.py`, the include order doesn't matter because each sub-router has its own prefix space. But within `search_collection.py`, the order of `@router.post()` decorators matters.

---

### Step 1: Extract shared MCP search helpers
**File:** `kapsula/presentation/mcp/tools/_search_helpers.py`

Move shared helper functions from `search.py` that are used by multiple tool groups:
- `_run_search_documents_text`
- `_run_intelligent_collection_search`  
- `_log_search_miss`
- `_get_topic_card_summary`
- `_execute_search_job`
- `_execute_intelligent_search_job`

These become public functions (no underscore) since they're shared across modules:
```python
async def run_search_documents_text(query, top_k, context_mode, ...) -> str: ...
async def run_intelligent_collection_search(query, top_k, ...) -> str: ...
def log_search_miss(db, query, collection_id, result_count, results) -> None: ...
def get_topic_card_summary(db, collection_db_id) -> str: ...
```

**Verify:** `python -c "from kapsula.presentation.mcp.tools._search_helpers import run_search_documents_text"`

---

### Step 2: Split MCP tools into sub-modules
**Files to create:**

`kapsula/presentation/mcp/tools/search_documents.py`:
```python
def register_search_document_tools(mcp: FastMCP):
    @mcp.tool(name="search_documents", ...)
    async def search_documents(...): return await run_search_documents_text(...)
    
    @mcp.tool(name="search_collection", ...)
    async def search_collection(...): return await run_search_documents_text(...)
    
    @mcp.tool(name="search_document", ...)
    async def search_document(...): ...
```

`kapsula/presentation/mcp/tools/search_intelligent.py`:
```python
def register_search_intelligent_tools(mcp: FastMCP):
    @mcp.tool(name="intelligent_search", ...)
    async def intelligent_search(...): return await run_intelligent_collection_search(...)
    
    @mcp.tool(name="intelligent_search_document", ...)
    async def intelligent_search_document(...): ...
```

`kapsula/presentation/mcp/tools/search_background.py`:
```python
def register_search_background_tools(mcp: FastMCP):
    @mcp.tool(name="start_search_documents", ...)
    async def start_search_documents(...): ...
    
    @mcp.tool(name="get_search_progress", ...)
    def get_search_progress(...): ...
    
    @mcp.tool(name="get_search_results", ...)
    def get_search_results(...): ...
    
    # + cancel_search, start_intelligent_search, get_intelligent_search_progress, get_intelligent_search_results
```

**Verify:** Each file imports only what it needs — `_search_helpers`, `_shared`, DTOs, `fastmcp`.

---

### Step 3: Update MCP tools `__init__.py`
**File:** `kapsula/presentation/mcp/tools/__init__.py`

```python
def register_search_tools(mcp: FastMCP):
    from .search_documents import register_search_document_tools
    from .search_intelligent import register_search_intelligent_tools
    from .search_background import register_search_background_tools
    
    register_search_document_tools(mcp)
    register_search_intelligent_tools(mcp)
    register_search_background_tools(mcp)
```

Keep the old `search.py` as a deprecation re-export:
```python
# search.py
from .search_documents import register_search_document_tools
from .search_intelligent import register_search_intelligent_tools
from .search_background import register_search_background_tools
```

**Verify:** `python -c "from kapsula.presentation.mcp.tools import register_search_tools"`

---

### Step 4: Split API routes
**Files to create:**

`kapsula/presentation/api/routes/search_helpers.py`:
Move `extract_citation_from_result`.

`kapsula/presentation/api/routes/search_collection.py`:
- `search_across_collections` (`POST /collections`, `POST /search/collections`)
- `search_collection` (`POST /collections/{collection_id}`)
- `search_collection_by_query_param` (`POST /collection`)

`kapsula/presentation/api/routes/search_document.py`:
- `search_document` (`POST /search/{job_id}`)
- `intelligent_search_document` (`POST /intelligent_search/{job_id}`)

`kapsula/presentation/api/routes/search_intelligent.py`:
- `intelligent_search_across_collections` (`POST /intelligent_search/collections`)
- `intelligent_search_across_collections_streaming` (`POST /intelligent_search/collections/stream`)

Each creates its own `router = APIRouter()`.

**Verify:** Each file imports `from .search_helpers import extract_citation_from_result`.

---

### Step 5: Update API routes `__init__.py`
**File:** `kapsula/presentation/api/routes/__init__.py`

```python
from .search_collection import router as search_collection_router
from .search_document import router as search_document_router
from .search_intelligent import router as search_intelligent_router

api_router.include_router(search_collection_router, prefix="/search", tags=["Search"])
api_router.include_router(search_document_router, prefix="/search", tags=["Search"])
api_router.include_router(search_intelligent_router, prefix="/search", tags=["Search"])
```

Keep old `search.py` as re-export:
```python
from .search_collection import router
```

**Verify:** `python -c "from kapsula.startup.api import app; print([r.path for r in app.routes])"` — lists all expected paths.

---

### Step 6: Run full test suite
```bash
pytest tests/test_mcp/ -v
```

**Common mistake:** Route ordering matters in FastAPI — `POST /collections` must come before `POST /collections/{collection_id}`. Verify the order in `search_collection.py`.
