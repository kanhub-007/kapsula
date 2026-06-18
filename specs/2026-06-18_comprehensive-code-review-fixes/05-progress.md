# Progress Log — Comprehensive Code-Review Fixes

Status as of 2026-06-18. Baseline: 120 passed / 1 HF-network failure.
Final: **154 passed** / 1 HF-network failure (unchanged — environment-only).
`ruff check` and `black --check` both clean.

## Slice 1 — Critical correctness & security ✅
- **L1** — `NoOpBackgroundProcessor` added; `create_api_upload_document_use_case()`
  wires it; route dispatches once via `BackgroundTasks`. Pinned by
  `test_upload_exactly_once.py`.
- **L2** — streaming search `return`s after the error event.
- **L3** — `_client_ip(request)` helper in `presentation/api/_http.py`;
  both routes use it.
- **L4** — `run_intelligent_collection_search` split into thin wrapper +
  `_run_intelligent_collection_search` body with try/finally.
- **SE1** — `hmac.compare_digest` in `auth.py`. Test in
  `test_security_slice1.py`.
- **SE2** — `_Bm25Unpickler` allowlist in `loaders.py`. Test rejects
  `os.system` / `subprocess` payloads.
- **D3** — duplicate docstring removed from `format_search_results`.
- **SC3** — `logger` moved above helpers in `routes/documents.py`.

## Slice 2 — Tests for core orchestration ✅
- **T1.1** `test_hybrid_searcher.py` (7 tests).
- **T1.2** `test_intelligent_searcher.py` (8 tests).
- **T1.3** `test_multi_index_searcher.py` (7 tests, incl. SourceQuotaPolicy).
- **T1.4** `test_consolidation_runner.py` (5 tests, in-memory repo fake).
- **T1.5** `test_upload_exactly_once.py` (pins L1).
- **S1.5/S1.6** `test_security_slice1.py` (6 tests).

## Slice 3 — Architecture debt ✅
- **A1/S1** — `SearchDataAccess` retyped to return `SubDocumentRead` /
  `CollectionRead` / `DocumentRead` DTOs; ORM mappers added; account
  methods removed. `SearchMetadataBuilder._resolve_account_guid` reads
  the DTO field.
- **A2/S4** — `ConsolidationCardRepository` interface + SQL impl;
  `ConsolidationRunner` rewritten to delegate all DB ops (617 → 425 lines,
  zero `session.add`/`session.query`).
- **A3/PE1/O3** — `MaintenanceStateManager` caches parsed JSON in memory;
  `increment_uploads` self-sufficient (docstring fixed); shared singleton
  via `create_maintenance_state_manager()`; 8 inline constructions replaced.
- **A5** — `os.makedirs(DATA_DIR)` deferred to `init_db()` (no import side effect).
- **A6/D5/O1** — `PrepareIntelligentSearchUseCase` + `SearchPreparation` DTO;
  API `_prepare_intelligent_search` and MCP `_db_work` both delegate to it.
- **D4** — `library_card_from_orm` mapper added; `SqlLibraryCardRepository` uses it.

## Slice 4 — Patterns & SOLID ✅ (P1/P3 partial — see notes)
- **P1/P3** — duplicated maintenance-tail (~30 lines × 2) extracted into
  `_run_ingestion_maintenance_tail`. Full Strategy-method extraction
  deferred (needs pipeline rewrite).
- **P2** — non-streaming `evaluate_and_answer_with_planning` consumes the
  streaming generator (single source of truth).
- **P4** — `BaseFusion` Template Method; `RRFFusion`/`WeightedFusion` subclass.
- **P6** — unused `CollectionRouteDecision` deleted; single `RouteDecision`.
- **P8** — handlers no longer subclass the `ElementHandler` Protocol.
- **S2** — `UploadDocumentUseCase._persist_and_dispatch` dedup.
- **S3** — `list_accounts` uses `joinedload` (N+1 fixed).

## Slice 5 — DRY, conventions, perf, remaining ✅
- **D1** — `_parse_json_safely`→`parse_json_safely`, `_gather`→`gather_flattened`,
  `_select`→`select_metadata`, `_NO_ANSWER_PHRASES`→`NO_ANSWER_PHRASES`,
  `_annotate_collection`→`annotate_collection`.
- **D2** — `DENSE_SIGNAL_THRESHOLD` single source in `quality_filter.py`.
- **P5** — `job_lifecycle` async context manager for background search jobs.
- **SC5** — `make_searcher: Callable[[str, str], Any]`; `db: Session` on
  `DeleteDocumentUseCase.execute`, `UploadDocumentUseCase.execute*`.
- **SC6** — chunking handlers: `el→element`, `s→state`, `tk→token_count`.
- **SC7** — `DATA_DIR = Path(__file__).resolve().parents[3] / "data"`.
- **PE3** — streaming route hoists `create_multi_index_searcher(db)` once.
- **O2** — `_shared.py` deprecation marker dropped (it's the active facade).

## Deferred → spec mapping

Each deferred item now has a home. Items marked **spec** got a full
spec under `specs/2026-06-18_*`; items marked **inline** are mechanical
enough (pattern obvious, low blast radius) that they are resolved by
the notes below rather than a standalone spec.

| Item | Resolution | Pattern |
|------|-----------|--------|
| **P1 full / P3 full / SC1** (upload God Methods, `tasks.py` size) | **spec:** `2026-06-18_upload-pipeline-refactor` | Template Method (skeleton) + Strategy (ingestion modes + flat/subdoc chunking) + Pipeline |
| **P7** (search returns `dict[str, Any]`) | **spec:** `2026-06-18_search-result-dtos` | DTO + Mapper |
| **SE3** (IDOR) | **resolved by decision** — see `2026-06-18_account-scoped-authorization` (single-tenant; accounts are organizational, not security boundaries; no code needed) | ADR (no pattern — decision only) |
| **O4** (`_deduplicate_states` legacy repair) | **spec:** `2026-06-18_maintenance-state-canonical-key` | One-shot idempotent migration |
| **A4 full** (`processing_status` module-global) | **inline** (mechanical; threading is safe — see note) | DI |
| **SC2** (MCP tool bodies in closures) | **inline** (mechanical) | Adapter |

### Inline resolution — A4 (`processing_status` DI)
The module-global dict in `upload_progress_store.py` is shared between
the request thread (use case calls `InMemoryProgressTracker.register_job`)
and the background thread (`tasks.py` writes via `UploadProgressTracker`).
This is safe: both reference the **same dict object** (imported from one
module), writes are whole-value replacements (`status[job_id] = {...}`),
and Python's GIL makes single-key dict assignment atomic — no
read-modify-write race. The refactor is therefore pure DI hygiene:

1. Add a `ProgressStore` parameter to `BackgroundProcessor.start_processing`
   and the task-runner signature; `ThreadPoolBackgroundProcessor` passes
   it through to the daemon thread.
2. Construct the shared `UploadProgressTracker(processing_status, logger)`
   once in `startup/` (it already constructs `InMemoryProgressTracker`);
   inject the same instance into the use case and into the task runner.
3. `tasks.py` and `_chunk_linker.py` take the tracker as a parameter
   instead of importing `processing_status` / building `_upload_progress`
   at module scope.
4. `get_processing_status(job_id)` route helper reads through the injected
   tracker.

No locking, no concurrency change — the dict stays shared; only the
*reach* to it becomes explicit. ~1–2 hours of work, no spec needed.

### Inline resolution — SC2 (MCP tool bodies)
Each `@mcp.tool`-decorated closure body becomes a module-level function
taking explicit `(db, repos, ...)`; the `@mcp.tool` wrapper shrinks to a
3-line Adapter that resolves deps and delegates. Pure mechanical extraction
following the Adapter pattern (the decorator adapts a plain, testable
function to an MCP tool). Benefits: tool bodies become directly unit-
testable without spinning up FastMCP; per-tool try/finally scaffolding
dedups naturally. Largest modules are `collections.py` (9 tools) and
`documents.py` (11 tools). ~3–4 hours, no spec needed.

All deferred items are lower-severity than Slice 1–3 and none are
correctness or security regressions. SE3 is **resolved by decision**
(single-tenant deployment; no inter-account isolation required) — see its
spec for the threat model and the future trigger that would reverse it.
