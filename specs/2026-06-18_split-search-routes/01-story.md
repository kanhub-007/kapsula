# Split Presentation Search Files (routes/search.py and mcp/tools/search.py)

## User Story
As a developer working on search functionality, I want each search variant (document, collection, intelligent) in its own focused file so that I can locate, modify, and test search behaviour without navigating 1200+ line monoliths.

## Context

Two files are 2-3x over the 500-line limit:

| File | Lines | Contains |
|------|-------|----------|
| `routes/search.py` | 1286 | 8 route handlers + citation extraction + node-type parsing + document structure building + 2 intelligent search orchestrations |
| `mcp/tools/search.py` | 775 | 12 tool registrations + background job runners + document structure building + intelligent search orchestration |

Both files have already had:
- `parse_node_type_filter` migrated to `core/domain/text_processing.py` (done)
- `document_structure_builder.py` created as shared helper (pending migration of call sites)

This spec covers the mechanical file-splitting — moving route/tool functions into separate files with no logic changes.

## Non-Goals
- Changing any search logic
- Refactoring the intelligent search orchestration (deferred to separate spec)
- Combining API routes and MCP tools — they remain separate adapters
- Adding new tests (existing test coverage is sufficient)

## Architecture Decision

**API routes split:**
```
presentation/api/routes/
├── search_document.py       — search_document, intelligent_search_document
├── search_collection.py     — search_across_collections, search_collection (both URL variants)
├── search_intelligent.py    — intelligent_search_across_collections, streaming variant
├── search_helpers.py        — extract_citation_from_result
└── __init__.py              — imports and includes all sub-routers
```

**MCP tools split:**
```
presentation/mcp/tools/
├── search_documents.py      — search_documents, search_collection, search_document
├── search_intelligent.py    — intelligent_search, intelligent_search_document
├── search_background.py     — start_search_documents, get_search_progress, 
│                              get_search_results, cancel_search,
│                              start_intelligent_search, get_intelligent_search_progress,
│                              get_intelligent_search_results
└── __init__.py              — register_search_tools imports all sub-modules
```

The `register_search_tools(mcp)` function stays in `__init__.py` and calls `register_*_tools(mcp)` from each sub-module.
