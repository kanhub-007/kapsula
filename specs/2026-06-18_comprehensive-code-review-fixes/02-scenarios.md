# Scenarios — Comprehensive Code-Review Fixes

Scenarios are grouped by slice. Within each slice, ordered by MoSCoW
priority. Each scenario lists the finding IDs it closes.

---

## Slice 1 — Critical correctness & security quick wins

### Scenario S1.1: HTTP upload runs background processing exactly once
**Priority:** Must
**Closes:** L1
**Slice:** 1

**Gherkin:**
  Given an HTTP `POST /documents/upload` request with a valid `.md` file
  When  the route handler returns
  Then  `process_document_with_subdocuments` is invoked exactly once for that job_id
  And   exactly one `Chunk` row per chunk is persisted
  And   exactly one FAISS and one BM25 document index file is written

**Verify (Classical, black-box):**
- The route calls `use_case.execute_from_content(...)` and does **not**
  additionally call `background_tasks.add_task(...)`.
- `UploadDocumentUseCase` is wired (in `startup/`) with a real
  `ThreadPoolBackgroundProcessor` for the MCP path and a
  `NoOpBackgroundProcessor` for the API path (so the API route keeps
  FastAPI `BackgroundTasks` as the single dispatch point, per the
  `wire-upload-usecase` spec).
- Integration test: upload via the MCP tool path and assert
  `_chunk_repo.count_by_document` equals the chunker's chunk count.

### Scenario S1.2: Streaming intelligent search returns after error
**Priority:** Must
**Closes:** L2
**Slice:** 1

**Gherkin:**
  Given the streaming endpoint and no collections exist for `account_id`
  When  `_prepare_intelligent_search` raises `HTTPException(404)`
  Then  exactly one `error` SSE event is yielded
  And   no `UnboundLocalError` is raised
  And   the generator terminates

**Verify:** unit test feeding an empty collection list asserts the event
stream is `[{event_type: error, ...}]` and the generator stops.

### Scenario S1.3: `request.client` is None-safe everywhere
**Priority:** Must
**Closes:** L3
**Slice:** 1

**Gherkin:**
  Given a request whose `request.client` is None
  When  any route reads the client IP
  Then  the value `"unknown"` is used
  And   no `AttributeError` is raised

**Verify:** grep confirms every `request.client.host` reads through a
single `_client_ip(request)` helper.

### Scenario S1.4: MCP search helper closes its own DB on every path
**Priority:** Must
**Closes:** L4
**Slice:** 1

**Gherkin:**
  Given `run_intelligent_collection_search` opened its own DB session
  When  the search body raises any exception
  Then  the DB session is closed (try/finally)

### Scenario S1.5: API-key comparison is constant-time
**Priority:** Must
**Closes:** SE1
**Slice:** 1

**Gherkin:**
  Given `KAPSULA_API_KEY` is set
  When  a request presents a key
  Then  comparison uses `hmac.compare_digest`
  And   a mismatch still yields 401

**Verify:** existing `test_api_auth.py` stays green; add a test that
asserts `hmac` is the comparison path.

### Scenario S1.6: BM25 index loader rejects unexpected pickle types
**Priority:** Should
**Closes:** SE2
**Slice:** 1

**Gherkin:**
  Given a `.bm25` / `.pkl` index file written by kapsula
  When  `load_bm25_index` reads it
  Then  the `BM25Plus` object and `texts` list are returned
  And   a pickled object whose globals are outside an explicit allowlist
        (`rank_bm25.BM25Plus`, `rank_bm25.BM25Okapi`, built-in containers)
        raises on load instead of executing arbitrary code

**Verify:** unit test writes a real index, loads it, then writes a
pickle whose payload is `os.system` and asserts loading raises.

### Scenario S1.7: Duplicate docstring removed; logger declared before use
**Priority:** Could
**Closes:** D3, SC3
**Slice:** 1

**Gherkin:**
  Given `format_search_results` and `routes/documents.py`
  When  audited
  Then  each public function has exactly one docstring
  And   `logger` is bound before any helper that references it

---

## Slice 2 — Tests for core orchestration

### Scenario S2.1: `HybridSearcher` behavioural tests
**Priority:** Must
**Closes:** T1.1
**Slice:** 2

**Verify (Classical, fakes at boundaries):**
- `FakeRetriever`, `FakeFusion`, `FakeReranker` (no mocks, no
  `assert_called`).
- Assert: dense+sparse are gathered concurrently, fusion output order is
  preserved, `node_type_filter` drops non-matching results,
  `sub_document_id` is stamped onto every result, `rerank=False` path
  returns the fused top-k unchanged.

### Scenario S2.2: `IntelligentSearcher` behavioural tests
**Priority:** Must
**Closes:** T1.2
**Slice:** 2

**Verify:**
- `FakeChatClient` returns canned JSON for evaluate / combine prompts.
- Cases: empty search results → "No search results" answer; context
  truncation respects `max_context_length`; `_NO_ANSWER_PHRASES` flips
  `has_answer=False`; planning happy path with 2 sub-queries aggregates
  sub-answers; combine-failure returns `has_answer=False` without
  raising.

### Scenario S2.3: `MultiIndexSearcher` behavioural tests
**Priority:** Must
**Closes:** T1.3
**Slice:** 2

**Verify:**
- `FakeSearchDataAccess`, `FakeCollectionSearchStrategy`, fake per-index
  searcher injected via `make_searcher`.
- Cases: no sub-documents → empty list; aggregate fast-path returns when
  a strategy yields non-None; route-metadata is attached to every
  result; quota policy truncates to `top_k`.

### Scenario S2.4: `ConsolidationRunner` behavioural tests
**Priority:** Must
**Closes:** T1.4 (depends on A2)
**Slice:** 2 (after Slice 3 A2)

**Verify:**
- `FakeChatClient`, in-memory `ConsolidationCardRepository`.
- Cases: no extractive cards → empty result; topic clustering yields
  topic cards linked via `CardReference`; importance is clamped to
  `[0,1]`; a failing topic-card step does not abort the whole run;
  `_record_run` persists the run row.

### Scenario S2.5: End-to-end upload exactly-once test
**Priority:** Must
**Closes:** T1.5, pins L1
**Slice:** 2

**Verify:**
- In-memory SQLite, fake embedder returning deterministic vectors, temp
  `DATA_DIR`. Upload a small `.md` via the wired use case. Assert:
  chunk count == chunker output length; exactly one FAISS + one BM25
  file per document; `processing_status[job_id]["status"] == "completed"`.

---

## Slice 3 — Architecture debt

### Scenario S3.1: `SearchDataAccess` returns typed read-models, not ORM
**Priority:** Must
**Closes:** A1, S1
**Slice:** 3

**Gherkin:**
  Given `MultiIndexSearcher` calls `data.get_sub_documents(...)`
  When  the result is consumed
  Then  it is a `SubDocumentRead` DTO (or domain entity), never a SQLAlchemy ORM instance
  And   `get_account_by_name` / `save_account` are removed from `SearchDataAccess`

**Verify:** type the Protocol; mappers run at the SQL impl boundary; no
`from kapsula.infrastructure.data.tables` import in
`core/application/use_cases/multi_index_searcher.py`.

### Scenario S3.2: `ConsolidationRunner` writes through a repository
**Priority:** Must
**Closes:** A2, S4
**Slice:** 3

**Gherkin:**
  Given `ConsolidationRunner.run()`
  When  it persists topic / evolution / gap cards, card references, or the run row
  Then  it calls methods on an injected `ConsolidationCardRepository`
  And   `ConsolidationRunner` contains zero `session.add(...)` / `session.query(...)` calls

**Verify:** `grep "session\." consolidation_runner.py` returns only
reads that the repository does not yet own; new
`ConsolidationCardRepository` interface lives in `core/domain/interfaces/`;
SQL impl + mapper in `infrastructure/repositories/data/`.

### Scenario S3.3: `MaintenanceStateManager` is injected, not constructed inline
**Priority:** Must
**Closes:** A3, PE1, O3, O4
**Slice:** 3

**Gherkin:**
  Given any caller of maintenance state
  When  it needs the manager
  Then  it receives it via constructor injection (or a documented module-level cached singleton in MCP tool modules)
  And   no `MaintenanceStateManager()` literal appears outside `startup/`
  And   the parsed JSON state is cached in memory and only flushed on write

**Verify:** grep shows zero inline constructions in non-startup layers;
`increment_uploads` is self-sufficient (no "call mark_collection_stale
first" temporal coupling); `_deduplicate_states` removed after a
one-shot canonical-key migration.

### Scenario S3.4: `processing_status` accessed via injected tracker
**Priority:** Should
**Closes:** A4
**Slice:** 3

**Gherkin:**
  Given `tasks.py` and routes that read live progress
  When  they need progress
  Then  they go through an injected `ProgressStore` (the existing `UploadProgressTracker` wrapping `processing_status`)
  And   the module-global `processing_status` dict is only constructed in `startup/`

### Scenario S3.5: Import-time side effects removed
**Priority:** Should
**Closes:** A5
**Slice:** 3

**Gherkin:**
  Given `import kapsula.startup.api`
  When  the import completes
  Then  no FastAPI app, no SQLAlchemy engine, and no `data/` directory are created
  And   `app` is obtained by calling `create_app()` explicitly

**Verify:** test that imports the module and asserts
`os.path.exists(DATA_DIR)` is unchanged and no `app` attribute exists;
`run_api.py` calls `create_app()`.

### Scenario S3.6: Shared intelligent-search preparation
**Priority:** Should
**Closes:** A6, D5, O1
**Slice:** 3

**Gherkin:**
  Given the API streaming/non-streaming routes and the MCP intelligent tool
  When  they prepare a search
  Then  they call a single `PrepareIntelligentSearchUseCase` returning a `SearchPreparation` DTO
  And   `_prepare_intelligent_search` and `_search_helpers._db_work` are removed

---

## Slice 4 — Patterns & SOLID

### Scenario S4.1: Ingestion strategies encapsulate their steps
**Priority:** Should
**Closes:** P1, P3 (partly)
**Slice:** 4

**Gherkin:**
  Given `FastUploadIngestionStrategy`, `IndexedUploadIngestionStrategy`, `FullUploadIngestionStrategy`
  When  the upload pipeline runs
  Then  each strategy implements `build_indexes(ctx)`, `run_collection_maintenance(ctx)`, `finalize(ctx)`
  And   `tasks.py` contains zero `if ingestion_strategy.<flag>:` branches

### Scenario S4.2: Streaming / non-streaming intelligent search share a core
**Priority:** Should
**Closes:** P2
**Slice:** 4

**Gherkin:**
  Given `IntelligentSearcher`
  When  refactored
  Then  a private `_run_plan(...)` (or the streaming generator) is the single source
  And   the non-streaming variant consumes it without duplicating sub-answer aggregation

### Scenario S4.3: Fusion uses a Template Method
**Priority:** Could
**Closes:** P4
**Slice:** 4

**Gherkin:**
  Given `RRFFusion` and `WeightedFusion`
  When  refactored
  Then  a `BaseFusion.fuse()` skeleton handles map-build + sort + quality-filter
  And   subclasses override only `_dense_score` / `_sparse_score`

### Scenario S4.4: Search results are DTOs, not `dict[str, Any]`
**Priority:** Should
**Closes:** P7
**Slice:** 4

**Gherkin:**
  Given `MultiIndexSearcher.search_*` and `IntelligentSearcher.evaluate_and_answer*`
  When  they return
  Then  they return `SearchHit` / `IntelligentSearchResult` DTOs
  And   the presentation layer maps DTO → Pydantic without string-keyed splat

### Scenario S4.5: Upload use-case dedup; routes N+1 fix; ISP split
**Priority:** Should
**Closes:** S1 (dup with S3.1), S2, S3
**Slice:** 4

**Gherkin:**
  Given `UploadDocumentUseCase.execute` and `execute_from_content`
  When  refactored
  Then  a private `_dispatch(...)` holds the shared body
  And   `list_accounts` issues a single query with eager loading

### Scenario S4.6: Element handler is a Protocol, not a base class
**Priority:** Could
**Closes:** P8
**Slice:** 4

**Verify:** handlers no longer subclass `ElementHandler`; the Protocol is
used only for type hints.

### Scenario S4.7: `RouteDecision` collapsed to one class
**Priority:** Could
**Closes:** P6
**Slice:** 4

**Verify:** single `RouteDecision` dataclass; both selector families use it.

---

## Slice 5 — DRY, conventions, perf, remaining

### Scenario S5.1: Cross-module helpers are public
**Priority:** Should
**Closes:** D1
**Slice:** 5

**Verify:** `_parse_json_safely` → `parse_json_safely`;
`_gather`/`_select` → `gather_flattened`/`select_metadata`;
`_NO_ANSWER_PHRASES` → `NO_ANSWER_PHRASES`;
`_annotate_collection` → `annotate_collection`. No leading-underscore
symbol is imported across modules.

### Scenario S5.2: Single source of truth for dense threshold
**Priority:** Could
**Closes:** D2
**Slice:** 5

**Verify:** `DENSE_SIGNAL_THRESHOLD` defined once in
`core/domain/quality_filter.py`; presenter imports it.

### Scenario S5.3: `library_card_from_orm` mapper
**Priority:** Could
**Closes:** D4
**Slice:** 5

**Verify:** `SqlLibraryCardRepository.find_collection_card` uses the mapper.

### Scenario S5.4: Background job lifecycle decorator
**Priority:** Could
**Closes:** P5
**Slice:** 5

**Verify:** `_execute_search_job` / `_execute_intelligent_search_job`
share a `with job_lifecycle(manager, job, label):` context manager.

### Scenario S5.5: MCP tool bodies extracted; import hygiene
**Priority:** Could
**Closes:** SC2, SC4
**Slice:** 5

**Verify:** per-tool bodies are module-level functions taking explicit
`(db, repos)`; all imports grouped at the top of each file.

### Scenario S5.6: Type annotations on all public surfaces
**Priority:** Should
**Closes:** SC5
**Slice:** 5

**Verify:** `make_searcher`, `searcher_factory`, `db` params on use
cases, and all `SearchDataAccess` Protocol methods are typed.

### Scenario S5.7: Readable chunking-handler names; robust DATA_DIR
**Priority:** Could
**Closes:** SC6, SC7
**Slice:** 5

**Verify:** `el → element`, `s → state`, `tk → token_count`;
`DATA_DIR` uses `Path(__file__).resolve().parents[3]`.

### Scenario S5.8: Hoist searcher construction; remove deprecated facade
**Priority:** Could
**Closes:** PE3, O2
**Slice:** 5

**Verify:** `create_multi_index_searcher(db)` called once per request,
not per sub-query; `_shared.py` either dropped or its deprecation
removed.

---

## Cross-cutting verify (every slice)

- `.venv/Scripts/python.exe -m pytest tests/ -q` → 120+ passing, the
  HF-network test may still fail in CI.
- `.venv/Scripts/python.exe -m ruff check kapsula/ tests/` → 0 errors.
- `.venv/Scripts/python.exe -m black --check kapsula/ tests/` → clean.
