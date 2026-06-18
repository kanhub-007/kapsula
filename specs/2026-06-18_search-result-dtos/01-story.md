# Search Result DTOs

## User Story
As a maintainer of kapsula, I want the search and intelligent-search use
cases to return typed DTOs instead of `dict[str, Any]`, so that the
application↔presentation boundary is schema-driven (no magic-string key
access), the API/MCP presenters cannot drift, and IDE/refactoring support
covers the result shapes.

## Context

Today the search stack returns untyped dicts everywhere:

- `MultiIndexSearcher.search_subdocuments / search_single_index /
  search_collections` → `list[dict[str, Any]]`.
- `IntelligentSearcher.evaluate_and_answer*` → `dict[str, Any]` with
  keys `answer`, `has_answer`, `relevant_results`, `total_evaluated`,
  `plan`, `sub_answers`, `search_results`, `error`.

A `grep` counts **111 dict-key access sites** (`result["..."]`,
`result.get(...)`, `event["data"]`) across the presenters
(`search_presenter.py` ×2, `search_document.py`, `search_collection.py`,
`search_intelligent.py`, `search_helpers.py`, MCP search tools) and the
use cases themselves. The API route does
`SubAnswer(**sub_answer)` — an unvalidated splat that will silently
break if a key is renamed.

This is the **DTO** + **Mapper** case from the decision tree (Q5: "data
crossing layer boundaries"). The DTO shapes are already sketched in the
comprehensive-review spec's `03-domain.md`; this spec defines them
exactly and sequences the migration so no slice leaves the presenters
broken.

## Pattern decision

1. **DTO** (Q5) — pure dataclasses in `core/application/dto/` for every
   result crossing the application→presentation boundary.
2. **Mapper** (Q5) — the use case builds the DTO; the presenter maps
   DTO → Pydantic model (API) or formatted string (MCP). The mapping is
   the only place that knows the wire shape.
3. **DI** — unchanged; DTOs are constructed inside the use cases.

**Rejected:** reusing the API Pydantic models as the use-case return
type — that would couple the application layer to FastAPI/Pydantic
(layer violation). DTOs stay framework-free.

## Non-Goals
- Changing the wire/API response shape (Pydantic models stay identical;
  clients see no diff).
- Changing the search algorithms, fusion, or reranking.
- Typed return for `context_expansion` internals (leaf helper; can stay
  dict internally as long as the use-case boundary returns a DTO).
- The MCP `format_search_results` plain-text contract (it consumes the
  DTO but its output string is unchanged).

## Slices
- **Slice 1** — Define `SearchHit` + mapper; migrate
  `MultiIndexSearcher` returns. Presenters read DTO fields.
- **Slice 2** — Define `SubAnswer`, `SearchPlan`,
  `IntelligentSearchResult`; migrate `IntelligentSearcher` returns;
  replace `SubAnswer(**sub_answer)` splat with explicit mapping.
