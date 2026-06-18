# Implementation Guide — Comprehensive Code-Review Fixes

Ordered by slice. Each step ends with `pytest` + `ruff` + `black` clean.
Run from the repo root with `.venv/Scripts/python.exe`.

## Slice 1 — Critical correctness & security quick wins

### Step 1.1 (L1): Single dispatch for HTTP upload
**File:** `kapsula/presentation/api/routes/documents.py`,
`kapsula/startup/__init__.py`,
`kapsula/core/domain/interfaces/background_processor.py`,
`kapsula/infrastructure/repositories/processing/background_processor.py`

- Add a `NoOpBackgroundProcessor(BackgroundProcessor)` whose
  `start_processing` is a no-op (infrastructure).
- Add `create_api_upload_document_use_case()` in `startup/__init__.py`
  that wires `NoOpBackgroundProcessor`.
- Keep `create_upload_document_use_case()` (real processor) for MCP.
- In `routes/documents.py`, switch to `create_api_upload_document_use_case()`
  and **delete** the `background_tasks.add_task(...)` block.
- Keep the `BackgroundTasks` parameter only if other tasks need it;
  otherwise drop it.

**Verify:** `pytest tests/test_application/test_upload_document.py -q`
+ new test in Slice 2 (S2.5).

### Step 1.2 (L2): Streaming search returns after error
**File:** `kapsula/presentation/api/routes/search_intelligent.py`

- In `event_generator`, after yielding the `'No collections available'`
  error event, `return` immediately.
- Remove the duplicated `# Step 4 & 5` comment.

**Verify:** new unit test `test_streaming_returns_after_prepare_error`.

### Step 1.3 (L3): `_client_ip(request)` helper
**Files:** `kapsula/presentation/api/routes/accounts.py`,
`kapsula/presentation/api/routes/collections.py`.

- Add `def _client_ip(request) -> str: return request.client.host if request.client else "unknown"`
  in each module (or a shared `presentation/api/_http.py`).
- Replace all bare `request.client.host` reads.

**Verify:** grep `request.client.host` returns only the helper body.

### Step 1.4 (L4): try/finally in MCP search helper
**File:** `kapsula/presentation/mcp/tools/_search_helpers.py`

- Wrap the body of `run_intelligent_collection_search` after `db = _get_db()`
  in `try/finally`; move `if own_db: db.close()` into `finally`.

### Step 1.5 (SE1): constant-time API-key compare
**File:** `kapsula/presentation/api/auth.py`

- `import hmac`.
- Replace `presented != expected` with
  `not hmac.compare_digest(presented or "", expected)`.

**Verify:** `pytest tests/test_presentation/test_api_auth.py -q` + new
test asserting `hmac` path.

### Step 1.6 (SE2): restricted BM25 unpickler
**File:** `kapsula/infrastructure/repositories/indexing/loaders.py`

- Define `_Bm25Unpickler(pickle.Unpickler)` with `find_class` allowlist:
  `rank_bm25.BM25Plus`, `rank_bm25.BM25Okapi`, and anything under
  `collections` / builtins.
- `load_bm25_index` uses `_Bm25Unpickler(f).load()`.

**Verify:** new test `test_bm25_loader_rejects_unsafe_pickle`.

### Step 1.7 (D3, SC3): docstring + logger
**Files:** `kapsula/presentation/mcp/search_presenter.py`,
`kapsula/presentation/api/routes/documents.py`.

- Delete the second docstring in `format_search_results`.
- Move `logger = get_logger(__name__)` above the `_require_*` helpers.

**Verify:** `ruff check` + visual.

---

## Slice 2 — Tests for core orchestration

Add one test file per class under `tests/test_application/` and
`tests/test_infrastructure/`. Use Classical school (fakes, no mocks,
assert on outcomes). For each, the corresponding production code may
need minor constructor-parameter additions (e.g. inject `make_searcher`).

### Step 2.1 (T1.1): `tests/test_application/test_hybrid_searcher.py`
- `FakeRetriever`, `FakeFusion`, `FakeReranker`.
- 5 cases per scenario S2.1.

### Step 2.2 (T1.2): `tests/test_application/test_intelligent_searcher.py`
- `FakeChatClient` with a queue of canned responses.
- Cases per scenario S2.2.

### Step 2.3 (T1.3): `tests/test_application/test_multi_index_searcher.py`
- `FakeSearchDataAccess` returning `SubDocumentRead`/`CollectionRead`
  DTOs (added in Slice 3; for this test use lightweight stand-ins until
  then, then update).

### Step 2.4 (T1.4): `tests/test_infrastructure/test_consolidation_runner.py`
- After Step 3.2; `InMemoryConsolidationCardRepository`.

### Step 2.5 (T1.5): `tests/test_application/test_upload_pipeline.py`
- In-memory SQLite, `FakeEmbedder`, temp DATA_DIR; assert exactly-once.

---

## Slice 3 — Architecture debt

### Step 3.1 (A1, S1): typed `SearchDataAccess` + read-models
**Files:** new DTOs in `core/application/dto/`; retype
`core/domain/interfaces/search_data_access.py`;
update `SqlSearchDataAccess` to map through mappers; add
`sub_document_from_orm_to_read`, etc. in `mappers.py`; update
`MultiIndexSearcher` + `SearchMetadataBuilder` + `context_expansion.py`
to consume read-models; remove `get_account_by_name`/`save_account`.

**Common mistake:** the ORM leak is wide — every `r.get("...")` in
`multi_index_searcher.py` and `context_expansion.py` must be re-checked.

### Step 3.2 (A2, S4): `ConsolidationCardRepository`
**Files:** new interface `core/domain/interfaces/consolidation_card_repository.py`;
new impl `infrastructure/repositories/data/sql_consolidation_card_repository.py`;
mapper additions in `mappers.py`; rewrite `ConsolidationRunner` to take
the repository + `session_factory` and contain no `session.add/query`;
update `presentation/upload/collection_maintenance_runner.py` wiring.

### Step 3.3 (A3, PE1, O3, O4): inject `MaintenanceStateManager`
**Files:** `maintenance_state_manager.py` (cache parsed JSON; make
`increment_uploads` self-sufficient; remove `_deduplicate_states`;
single canonical GUID key); add `create_maintenance_state_manager()` in
`startup/`; inject into `UploadDocumentUseCase`, `DeleteDocumentUseCase`,
`CollectionMaintenanceRunner`; module-level cached singleton in MCP tool
modules.

### Step 3.4 (A4): inject `ProgressStore`
**Files:** `tasks.py` takes an `UploadProgressTracker` (or the
`processing_status` dict) explicitly; `get_processing_status` route
helper reads through the tracker.

### Step 3.5 (A5): remove import-time side effects
**Files:** `startup/api.py` (drop `app = create_app()`; `run_api.py`
calls `create_app()`); `run_api.py` / `run_all.py` updated.

**Common mistake:** uvicorn `"kapsula.startup.api:app"` string needs an
`app` object — switch to `create_app()` callable or keep a thin
`app = create_app()` only behind `if __name__ == "__main__"`.

### Step 3.6 (A6, D5, O1): `PrepareIntelligentSearchUseCase`
**Files:** new use case in
`core/application/use_cases/prepare_intelligent_search.py`; new
`SearchPreparation` DTO; delete
`presentation/api/routes/_intelligent_search_prepare.py` body and the
`_db_work` block in `_search_helpers.py`; wire in `startup/`.

---

## Slice 4 — Patterns & SOLID

### Step 4.1 (P1, P3): real ingestion strategies + upload pipeline
- `UploadIngestionStrategy` gains `build_indexes(ctx)`,
  `run_collection_maintenance(ctx)`, `finalize(ctx)`.
- Extract `UploadPipeline` (orchestration) into
  `core/application/use_cases/upload/upload_pipeline.py`; `tasks.py`
  becomes a thin adapter that builds the pipeline + calls `.run()`.

### Step 4.2 (P2): deduplicate intelligent-search methods
- Private `_run_plan_async(...)` async generator; non-streaming variant
  collects events and returns the `final_answer` payload.

### Step 4.3 (P4): fusion Template Method
- `BaseFusion` in `core/domain/fusion/base_fusion.py`; `RRFFusion` /
  `WeightedFusion` subclass it.

### Step 4.4 (P7): search result DTOs
- Introduce `SearchHit`, `SubAnswer`, `SearchPlan`,
  `IntelligentSearchResult`; update `MultiIndexSearcher`,
  `IntelligentSearcher`, and both presenters.

### Step 4.5 (S2, S3): upload dedup + list_accounts N+1
- `_dispatch` private helper in `UploadDocumentUseCase`.
- `list_accounts` uses `joinedload(OrmAccount.collections)`.

### Step 4.6 (P8): handlers drop the Protocol base
- Remove `(ElementHandler)` inheritance from the five handlers.

### Step 4.7 (P6): single `RouteDecision`
- Delete `collection_route_decision.py`; both selector families import
  `RouteDecision` from `route_decision.py`.

---

## Slice 5 — DRY, conventions, perf, remaining

### Step 5.1 (D1): promote private helpers
- `parse_json_safely`, `gather_flattened`, `select_metadata`,
  `NO_ANSWER_PHRASES`, `annotate_collection`.

### Step 5.2 (D2): `DENSE_SIGNAL_THRESHOLD` single source
### Step 5.3 (D4): `library_card_from_orm` mapper
### Step 5.4 (P5): `job_lifecycle` context manager
### Step 5.5 (SC2, SC4): MCP tool bodies extracted; imports grouped
### Step 5.6 (SC5): type annotations audit
### Step 5.7 (SC6, SC7): handler names; `DATA_DIR` path
### Step 5.8 (PE3, O2): hoist searcher; deprecate/remove `_shared.py`

---

## Common mistakes to watch for

- **L1 fix:** the MCP path MUST still dispatch via the use case — only
  the API path uses `NoOpBackgroundProcessor`. Inverting this regresses
  the MCP tool.
- **A1:** `context_expansion.py` reads `chunk.sub_document_id`,
  `chunk.chunk_index` from ORM `Chunk` — these must become read-model
  access or the expansion breaks.
- **SE2:** `rank_bm25.BM25Plus` pickles its internal `dict`/`ndarray`
  state — the allowlist must permit `numpy` core types and built-in
  containers or real indexes will fail to load.
- **A5:** `startup/api.py` exposing `app` is required by `Dockerfile` /
  `docker-compose.yml` — verify the deployment entrypoint still works.
