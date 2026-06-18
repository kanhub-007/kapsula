# Consolidate Document Structure Building Across Routes and MCP Tools

## User Story
As a developer modifying search behaviour, I want the document structure building logic (querying library cards, building section hierarchies) defined in ONE place so that I don't need to find and update 5+ identical code blocks across routes and MCP tools.

## Context

The pattern of querying `LibraryCard` with `level.in_(["level_1", "level_2", "level_3"])` and building `document_structure` dicts is duplicated in at least 5 locations:

| Location | Lines | Function |
|----------|-------|----------|
| `routes/search.py:363-406` | ~45 | `intelligent_search_across_collections` |
| `routes/search.py:721-765` | ~45 | `intelligent_search_across_collections_streaming` |
| `routes/search.py:1106-1156` | ~50 | `intelligent_search_document` |
| `mcp/tools/search.py:130-155` | ~25 | `_run_intelligent_collection_search` |
| `mcp/tools/search.py:660-690` | ~30 | `intelligent_search_document` |

A shared helper `kapsula/presentation/shared/document_structure_builder.py` was already created. The call sites need to be migrated to use it.

## Non-Goals
- Changing the structure dict format (must remain compatible with `QueryPlanner.plan_document_search()`)
- Changing the `LibraryCard` query logic
- Adding caching or performance optimisations (separate work)

## Architecture Decision

The `document_structure_builder.py` lives in `presentation/shared/` because it uses ORM models directly (CQRS-lite read exception). Both API routes and MCP tools import from this shared module.
