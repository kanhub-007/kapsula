# Scenarios — Split Search Files

---

### Scenario: All existing routes respond identically after splitting
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the search routes are moved to sub-modules
  When  any existing search endpoint is called
  Then  the response is byte-for-byte identical to before the split (modulo timestamps)
  And   all existing URL paths are preserved

**Verify:**
- `POST /search/collections` → same response
- `POST /search/collections/{collection_id}` → same response
- `POST /search/{job_id}` → same response
- `POST /search/intelligent_search/collections` → same response
- `POST /search/intelligent_search/{job_id}` → same response
- `POST /search/intelligent_search/collections/stream` → same SSE stream

---

### Scenario: Each sub-module file is under 500 lines
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the routes are split into sub-modules
  When  I check each file's line count
  Then  no file exceeds 500 lines
  And   each file contains only related routes (document, collection, or intelligent)

**Verify:**
```bash
wc -l kapsula/presentation/api/routes/search_document.py    # < 500
wc -l kapsula/presentation/api/routes/search_collection.py  # < 500
wc -l kapsula/presentation/api/routes/search_intelligent.py # < 500
wc -l kapsula/presentation/api/routes/search_helpers.py     # < 200
wc -l kapsula/presentation/mcp/tools/search_documents.py    # < 500
wc -l kapsula/presentation/mcp/tools/search_intelligent.py  # < 500
wc -l kapsula/presentation/mcp/tools/search_background.py   # < 500
```

---

### Scenario: Router registration is unchanged
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given `routes/__init__.py` imports the sub-routers
  When  the FastAPI app starts
  Then  all search routes are registered under the `/search` prefix

**Verify:**
```python
# routes/__init__.py
from .search_document import router as search_document_router
from .search_collection import router as search_collection_router
from .search_intelligent import router as search_intelligent_router

api_router.include_router(search_collection_router, prefix="/search", tags=["Search"])
api_router.include_router(search_document_router, prefix="/search", tags=["Search"])
api_router.include_router(search_intelligent_router, prefix="/search", tags=["Search"])
```
Check with `app.routes` that all paths are registered.

---

### Scenario: MCP tool registration is unchanged
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given `register_search_tools` is split across sub-modules
  When  the MCP server starts
  Then  all 12 search tools are registered with the same names and descriptions

**Verify:**
```python
# tools/__init__.py
def register_search_tools(mcp: FastMCP):
    from .search_documents import register_search_document_tools
    from .search_intelligent import register_search_intelligent_tools
    from .search_background import register_search_background_tools
    
    register_search_document_tools(mcp)
    register_search_intelligent_tools(mcp)
    register_search_background_tools(mcp)
```
Check `mcp.list_tools()` returns all 12 tool names.

---

### Scenario: Shared helpers are not duplicated
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given `_run_search_documents_text`, `_run_intelligent_collection_search`, `_log_search_miss`, `_get_topic_card_summary` are used by both document and intelligent search tools
  When  MCP tools are split into sub-modules
  Then  these helpers live in a shared `_search_helpers.py` imported by both sub-modules

**Verify:**
```bash
grep -rn "_run_search_documents_text" kapsula/presentation/mcp/tools/
# Should appear in _search_helpers.py (definition) and search_documents.py, search_background.py (imports)
# Should NOT appear duplicated
```

---

### Scenario: Existing imports from outside the module still work
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given external code imports from `kapsula.presentation.api.routes.search`
  When  the refactoring is deployed
  Then  specific named imports may break, but the `api_router` integration in `routes/__init__.py` is preserved

**Verify:**
```python
from kapsula.presentation.api.routes import api_router
# api_router still has all routes registered
```
Add deprecation re-exports in `routes/search.py` for any public symbols.

---

### Scenario: No circular imports introduced
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given the split sub-modules
  When  the application starts
  Then  no ImportError or circular-import warning is raised

**Verify:**
```bash
python -c "from kapsula.presentation.api.routes.search_collection import router"
python -c "from kapsula.presentation.api.routes.search_document import router"
python -c "from kapsula.presentation.api.routes.search_intelligent import router"
python -c "from kapsula.presentation.mcp.tools.search_documents import register_search_document_tools"
python -c "from kapsula.presentation.mcp.tools.search_intelligent import register_search_intelligent_tools"
```
All succeed without error.
