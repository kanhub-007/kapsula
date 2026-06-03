# Doc-Search MCP/API Search Improvement Plan

Date: 2026-06-02

## Current Diagnosis

Broad MCP search is not fundamentally broken. It is slow and timeout-prone because broad search currently does too many sequential routing/search operations.

Measured behavior for a broad query:

```text
search_documents("What is the adapter pattern?")
```

Observed cost:

```text
~25 LLM chat calls
~24 embedding calls
~60 seconds total
```

Targeted document search works fine:

```text
search_document(job_id, query)
→ ~2–3 seconds
```

The issue is mainly broad search across collections/documents/subdocuments.

## Main Problems to Solve

### 1. MCP Timeout/UX Problem

The Pi extension waits for a single final MCP response. If the search takes too long, it returns:

```text
MCP request timeout: tools/call
```

That timeout comes from:

```text
.pi/extensions/doc-search.ts
```

not from FastMCP or the Python search code.

### 2. Search Execution Problem

Broad search currently performs subdocument routing per document, often one LLM call per document.

Relevant files:

```text
doc_search/core/application/use_cases/multi_index_searcher.py
doc_search/core/application/use_cases/selectors/collection_selector.py
doc_search/core/application/use_cases/selectors/sub_document_selector.py
```

### 3. Search Quality Problem

We do not want to simply skip routing and search everything, because similar-but-wrong content can pollute the final `top_k`.

The goal is:

```text
Keep routing quality.
Reduce routing cost.
Improve async UX.
Improve final ranking against pollution.
```

## Target Architecture

Long-term ideal flow:

```text
User query
  ↓
Cheap metadata router over collection/document/subdocument cards
  ↓
LLM validates top routing candidates in one batched call
  ↓
Search selected indexes with FAISS/BM25
  ↓
Apply route-confidence weighting
  ↓
Apply per-source quotas
  ↓
Return final top_k
```

This should provide:

```text
Broad search without forcing job_id
Less wrong-collection pollution
Fewer LLM calls
Better MCP reliability
```

---

# Phase 1 — Quick Reliability and Observability Fixes

## Goal

Make current behavior easier to debug and less likely to timeout unexpectedly.

## Changes

### 1. Add Timing Logs Around MCP Requests

File:

```text
.pi/extensions/doc-search.ts
```

Add elapsed timing for each JSON-RPC request:

```text
initialize
tools/list
tools/call
```

Error should include elapsed time and configured timeout.

Example:

```text
MCP request timeout after 120000ms: tools/call
```

### 2. Use Method-Specific MCP Timeouts

Keep short timeouts for setup/listing, longer for search calls.

Example:

```ts
const timeoutMs =
  method === "tools/call"
    ? 300000
    : 30000;
```

Recommended initial values:

```text
initialize: 30s
tools/list: 30s
tools/call: 5min
```

### 3. Respect Pi Cancellation Signal

The registered tool receives:

```ts
execute(_toolCallId, params, signal, ...)
```

Use the signal to cancel the pending MCP request if the user aborts.

This prevents abandoned pending requests.

### 4. Add Backend Search Timing Logs

Files:

```text
doc_search/core/application/use_cases/multi_index_searcher.py
doc_search/core/application/use_cases/selectors/collection_selector.py
doc_search/core/application/use_cases/selectors/sub_document_selector.py
```

Log:

```text
collection routing time
subdocument routing time
number of selected collections
number of selected subdocuments
number of searched documents
number of HF chat calls
number of embedding calls if easy to track
total search time
```

## Acceptance Criteria

- Timeout errors tell us which MCP method timed out and after how long.
- Broad search no longer silently fails at 120s if it needs slightly longer.
- Cancelling a tool call does not leave the extension waiting on a dead request.
- Logs make it clear where time is spent.

---

# Phase 2 — Add Missing Search Granularity

## Goal

Provide useful middle-ground search tools besides “search everything” and “search one document”.

## Changes

### 1. Add Collection-Scoped API Search

New route option:

```text
POST /search/collections/{collection_id}
```

or query-param form:

```text
POST /search/collection?collection_id=...
```

### 2. Add MCP Tool: `search_collection`

New MCP tool:

```text
search_collection(
  collection_id: str,
  query: str,
  top_k: int = 10,
  rerank: bool = False,
  context_mode: str = "none",
  node_type_filter: str | None = None
)
```

### 3. Optional Compact Document Listing Helper

Existing tools already include:

```text
list_collections
get_collection
list_documents
```

But a compact helper could be useful:

```text
list_collection_documents(collection_id)
```

It should return names, statuses, chunk counts, and `job_id` values.

## Acceptance Criteria

- Pi can search a collection directly without needing an exact `job_id`.
- `search_collection` avoids cross-collection pollution.
- Search is faster than `search_documents` and broader than `search_document`.

---

# Phase 3 — MCP Async Job Mode

## Goal

Prevent long-running searches from being tied to one MCP request/response cycle.

This is especially useful for broad search and intelligent search.

## New MCP Tools

Add background job tools:

```text
start_search_documents
get_search_progress
get_search_results
cancel_search
```

Potential signatures:

```text
start_search_documents(
  query: str,
  top_k: int = 10,
  context_mode: str = "none",
  account_id: str | None = None,
  collection_id: str | None = None,
  routing_mode: str = "auto"
) -> search_job_id
```

```text
get_search_progress(search_job_id: str)
```

```text
get_search_results(search_job_id: str)
```

```text
cancel_search(search_job_id: str)
```

Also consider async versions for intelligent search:

```text
start_intelligent_search
get_intelligent_search_progress
get_intelligent_search_results
```

## Implementation Approach

In MCP tools module:

```text
doc_search/presentation/mcp/tools/__init__.py
```

Maintain an in-memory job registry:

```py
_search_jobs: dict[str, SearchJob]
```

Each job tracks:

```text
job_id
status: queued/running/completed/failed/cancelled
progress message
created_at
updated_at
result
error
task
```

Use:

```py
asyncio.create_task(...)
```

or a thread-safe background task pattern depending how FastMCP runs the tool.

## Acceptance Criteria

- `start_search_documents` returns quickly with a job id.
- Pi can poll progress.
- A long broad search can complete without hitting `tools/call` timeout.
- Cancelled jobs stop cleanly where practical.

---

# Phase 4 — Query Embedding Cache

## Goal

Avoid embedding the same query repeatedly during one broad search.

Current broad search embedded the same query many times.

## Candidate File

```text
doc_search/infrastructure/repositories/embedding/huggingface_embedder.py
```

## Approach

Add a small in-memory LRU cache for single-string queries.

Cache key:

```text
model endpoint + normalized query
```

Example behavior:

```py
embed("adapter pattern")
# first call: Hugging Face request

embed("adapter pattern")
# subsequent calls: cache hit
```

Keep cache small:

```text
128 or 256 entries
```

Only cache string queries, not large batch ingestion calls.

## Acceptance Criteria

- Broad search no longer makes one embedding call per document/subdocument for the same query.
- Search result quality remains unchanged.
- Cache can be cleared in tests.

---

# Phase 5 — Improve Routing Without Skipping It

## Goal

Keep routing as a quality gate, but make it cheaper and more accurate.

## 5.1 Keep Collection Routing as a Hard Gate

Collection routing is valuable and should remain.

Current file:

```text
doc_search/core/application/use_cases/selectors/collection_selector.py
```

Current output:

```text
comma-separated collection IDs
```

Later improvement: return structured data:

```json
{
  "collections": [
    {
      "id": 2,
      "confidence": 0.94,
      "reason": "Query asks about design pattern terminology."
    }
  ],
  "should_search_all": false
}
```

## 5.2 Replace Per-Document Subdocument Routing With Batched Routing

Current broad search effectively does:

```text
for each document:
  ask LLM which subdocuments to search
```

New approach:

```text
for selected collection:
  collect candidate subdocuments across documents
  ask LLM once which subdocuments to search
```

New selector concept:

```text
BatchedSubDocumentSelector
```

Possible file:

```text
doc_search/core/application/use_cases/selectors/batched_sub_document_selector.py
```

Input:

```py
[
  {
    "id": subdoc.id,
    "document_id": doc.id,
    "document_filename": doc.filename,
    "breadcrumb_key": subdoc.breadcrumb_key,
    "page_titles": [...],
    "summary": ...
  }
]
```

Output:

```json
{
  "subdocuments": [
    {
      "id": 10,
      "confidence": 0.98,
      "reason": "Directly about Adapter pattern."
    },
    {
      "id": 12,
      "confidence": 0.52,
      "reason": "Contains comparison to Adapter."
    }
  ]
}
```

## 5.3 Keep Fallback Behavior Safe

If LLM routing fails:

```text
fallback to cheap metadata candidates
```

Do not immediately “search everything” unless necessary.

## Acceptance Criteria

- Broad collection search reduces LLM routing calls dramatically.
- Query results remain collection-correct.
- If routing fails, search still returns reasonable results.

---

# Phase 6 — Cheap Metadata Pre-Router

## Goal

Reduce what we send to the LLM and improve routing consistency.

## Approach

Before LLM routing, rank candidate collections/documents/subdocuments using cheap local metadata.

Use:

```text
collection library cards
document library cards
subdocument cards
section titles
page titles
document filenames
breadcrumb keys
```

Scoring can start simple:

```text
BM25 over metadata strings
```

Later add embedding similarity over metadata cards.

## Candidate File

New use case:

```text
doc_search/core/application/use_cases/selectors/metadata_preselector.py
```

or:

```text
doc_search/core/application/use_cases/routing/metadata_router.py
```

## Flow

```text
all possible subdocuments
  ↓
cheap metadata pre-router
  ↓
top N candidates
  ↓
batched LLM validator
  ↓
hybrid search selected indexes
```

Initial defaults:

```text
max_candidates_for_llm = 30
min_candidates = 5
```

## Acceptance Criteria

- LLM prompts stay bounded even for large collections.
- Relevant subdocuments are included in candidate set.
- Search is faster and less token-heavy.

---

# Phase 7 — Route-Confidence Weighted Ranking

## Goal

Prevent similar-but-wrong sources from polluting final `top_k`.

## Current Issue

If we search too broadly, semantically similar chunks from the wrong source can rank highly.

## New Scoring

Each result should carry routing confidence:

```text
collection_route_confidence
document_route_confidence
subdocument_route_confidence
```

Then final score can be adjusted:

```text
final_score =
  retrieval_score
  * collection_route_confidence
  * subdocument_route_confidence
```

Or with softer weights:

```text
final_score =
  retrieval_score
  * (0.7 + 0.3 * collection_confidence)
  * (0.7 + 0.3 * subdocument_confidence)
```

The softer version avoids completely burying useful results when confidence is imperfect.

## Acceptance Criteria

- Wrong-collection/wrong-document hits are demoted.
- Correct routed sources dominate final `top_k`.
- Search result metadata includes route confidence for debugging.

---

# Phase 8 — Per-Source Quotas Before Final Top-K

## Goal

Avoid one noisy document/index dominating all final results.

## Approach

Before global top-k, apply source limits:

```text
max results per collection
max results per document
max results per subdocument
```

Example defaults:

```text
per_collection_limit = top_k * 3
per_document_limit = max(3, top_k // 2)
per_subdocument_limit = 3
```

Then globally sort/rerank after quotas.

## Acceptance Criteria

- Final results are more diverse.
- One document cannot flood all results.
- Relevant direct matches still appear first.

---

# Phase 9 — Parallelize Search Execution Safely

## Goal

Make broad search faster once routing is cheaper and bounded.

## Current Issue

In:

```text
doc_search/core/application/use_cases/multi_index_searcher.py
```

document search inside a collection currently loops sequentially.

## Change

Use bounded concurrency:

```py
semaphore = asyncio.Semaphore(DOCSEARCH_DOCUMENT_CONCURRENCY)
```

Env var:

```text
DOCSEARCH_DOCUMENT_CONCURRENCY=4
```

Potential defaults:

```text
local indexes: 4–8
HF-heavy path: 2–4
```

## Important

Do this after or alongside embedding cache and batched routing. Otherwise parallelization could hammer Hugging Face with too many simultaneous calls.

## Acceptance Criteria

- Broad search wall-clock time drops.
- No HF rate-limit spikes.
- Results are equivalent or better.

---

# Phase 10 — Routing Modes

## Goal

Expose behavior tradeoffs explicitly.

Add routing mode to API/MCP:

```text
routing_mode: "llm" | "fast" | "auto"
```

Suggested semantics:

```text
llm:
  use LLM collection/subdocument routing

fast:
  use metadata pre-router only, skip LLM subdocument validation

auto:
  use LLM for collection routing
  use metadata + batched LLM only when candidate set is ambiguous
```

Default should probably be:

```text
auto
```

## Acceptance Criteria

- Users can choose speed vs precision.
- MCP can use `auto` by default.
- Tests verify each routing mode.

---

# Phase 11 — Aggregate Indexes

## Goal

Long-term broad search should take seconds, not minutes.

## Architecture

Build higher-level indexes during ingestion:

```text
subdocument indexes
document indexes
collection indexes
account/global indexes
```

Then broad search can use:

```text
collection-level FAISS/BM25
```

instead of iterating over every document/subdocument index.

## Tradeoff

This is the largest change because it affects indexing/upload/update logic.

Relevant files likely include:

```text
doc_search/presentation/api/tasks.py
doc_search/infrastructure/repositories/indexing/document_index_builder.py
doc_search/infrastructure/data/tables/*
```

## Acceptance Criteria

- Searching a collection does not require opening every document/subdocument index.
- Broad collection search returns in seconds.
- Indexes update correctly on document upload/reprocessing.

---

# Recommended Implementation Order

## Sprint 1

```text
Phase 1: MCP timeout/logging/cancellation
Phase 2: search_collection
Phase 4: embedding cache
```

These are quick wins and low architectural risk.

## Sprint 2

```text
Phase 3: async MCP search jobs
```

This makes long-running search reliable even before all performance work is complete.

## Sprint 3

```text
Phase 5: batched subdocument routing
Phase 6: metadata pre-router
```

This attacks the biggest current cost: repeated LLM routing.

## Sprint 4

```text
Phase 7: route-confidence ranking
Phase 8: per-source quotas
Phase 9: bounded parallel search
```

This improves quality and speed together.

## Sprint 5

```text
Phase 10: routing modes
Phase 11: aggregate indexes
```

This gives long-term flexibility and performance.

---

# Minimal First Implementation

If we want the fastest meaningful improvement, start with these four changes:

```text
1. Add search_collection MCP/API tool
2. Add embedding cache
3. Add MCP async search jobs
4. Add batched subdocument routing
```

Expected benefits:

```text
less need to force job_id
fewer repeated HF calls
no MCP timeout pain
less routing overhead
```

Then add confidence scoring and quotas to improve result quality.

---

# Tracking Checklist

## Phase 1

- [x] Add elapsed timing to `.pi/extensions/doc-search.ts` requests.
- [x] Add method-specific timeouts.
- [x] Add cancellation handling via Pi `AbortSignal`.
- [x] Add backend routing/search timing logs.

## Phase 2

- [x] Add collection-scoped API route.
- [x] Add MCP `search_collection` tool.
- [x] Add compact collection document listing helper if needed.

## Phase 3

- [x] Add MCP search job registry.
- [x] Add `start_search_documents`.
- [x] Add `get_search_progress`.
- [x] Add `get_search_results`.
- [x] Add `cancel_search`.
- [x] Consider async intelligent-search job tools.

## Phase 4

- [x] Add single-query embedding cache.
- [x] Add cache size limit.
- [x] Add test/cache-clear support.

## Phase 5

- [x] Preserve collection routing.
- [x] Add batched subdocument selector.
- [x] Add safe fallback behavior.

## Phase 6

- [x] Add metadata preselector.
- [x] Rank subdocument candidates using metadata BM25.
- [x] Limit LLM candidate prompt size.

## Phase 7

- [x] Return route confidence from selectors.
- [x] Attach confidence metadata to results.
- [x] Apply route-confidence weighted scoring.

## Phase 8

- [x] Add per-source quota logic.
- [x] Tune collection/document/subdocument limits.

## Phase 9

- [x] Add bounded document search concurrency.
- [x] Add `DOCSEARCH_DOCUMENT_CONCURRENCY` env var.
- [ ] Validate no HF rate-limit problems.

## Phase 10

- [x] Add `routing_mode` to API DTOs/routes.
- [x] Add `routing_mode` to MCP tools.
- [x] Implement `llm`, `fast`, and `auto` behavior.

## Phase 11

- [x] Design aggregate index schema/storage.
- [x] Build collection-level indexes during ingestion.
- [ ] Build account/global indexes if needed.
- [x] Update broad search to use aggregate indexes.
