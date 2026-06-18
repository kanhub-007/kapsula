# Implementation Guide — Upload Pipeline Refactor

Ordered by slice. Each slice ends green: `pytest` + `ruff` + `black`.

## Slice 1 — Interfaces + context (no behaviour move)

### Step 1.1: `UploadPipelineContext`
**File:** `kapsula/core/application/dto/upload_pipeline_context.py`
- Dataclass with every field from the domain model table. Mutable.
- No behaviour.

### Step 1.2: Retype `UploadIngestionStrategy` + 3 impls
**Files:** `core/application/use_cases/upload/upload_ingestion_strategy.py`,
`fast_upload_ingestion_strategy.py`, `indexed_upload_ingestion_strategy.py`,
`full_upload_ingestion_strategy.py`.
- Protocol gains `build_indexes(ctx)`, `update_collection_summary(ctx)`,
  `rebuild_aggregates(ctx)`.
- Fast = three no-ops; Indexed = `build_indexes` real, other two no-ops;
  Full = all three real (move the bodies from `_build_document_indexes`,
  `update_collection_library_card`, `rebuild_collection_aggregate_index`
  invocations into the strategy — keep calling the same infrastructure
  helpers, just from inside the strategy method).
- Remove the three boolean flags.
- Update `UploadIngestionStrategyFactory.create` (unchanged signature;
  returns the new-shape objects).

**Common mistake:** the strategies now need `embedder`/`progress` to do
real work — read them from `ctx` inside the method, not from the
constructor (strategies must stay stateless/singleton-safe).

**Verify:** `grep "build_document_indexes\|update_collection_summary\|rebuild_aggregate_indexes" kapsula/` returns only the strategy files' no-op bodies, no callers.

---

## Slice 2 — Template Method skeleton

### Step 2.1: `ChunkingStrategy` + Flat + SubDocument impls
**Files:** `core/application/use_cases/upload/chunking_strategy.py`,
`flat_chunking_strategy.py`, `subdocument_chunking_strategy.py`.
- `FlatChunkingStrategy.extract_and_chunk(ctx)`: runs
  `extract_parent_sections` + `MarkdownChunker().chunk` +
  `add_citation_metadata_to_chunks`; sets `ctx.parent_sections`,
  `ctx.chunks`.
- `SubDocumentChunkingStrategy.extract_and_chunk(ctx)`: runs
  `extract_subdocuments`; if invalid, delegates to a held
  `FlatChunkingStrategy`; else loops breadcrumbs, creates `SubDocument`
  records, chunks each, sets `ctx.subdocs` + `ctx.chunks`.

### Step 2.2: `UploadPipeline` orchestrator
**File:** `core/application/use_cases/upload/upload_pipeline.py`.
- Constructor takes `(chunking, ingestion)`.
- `run(ctx)` calls the 5 private steps in order.
- Each step <50 lines; pulls everything from `ctx`.
- Persistence steps call the existing `_persist_chunks` /
  `_persist_parent_cards` / `_link_and_persist_subdoc_chunks` helpers
  (move them next to the pipeline or into a `ChunkPersistence`
  collaborator — they are file-level helpers today).

### Step 2.3: `startup/create_upload_pipeline(mode)`
**File:** `kapsula/startup/__init__.py`.
- Factory: picks `ChunkingStrategy` (SubDocument by default) +
  `UploadIngestionStrategy` (from mode) + wires deps into a context
  builder. Returns the pipeline.

### Step 2.4: Thin `tasks.py`
**File:** `kapsula/presentation/api/tasks.py`.
- `process_document_with_subdocuments(job_id, content, max_tokens, db, ingestion_mode)`:
  build `UploadPipelineContext` (deps from `startup/`), build pipeline,
  `pipeline.run(ctx)`, then the final completed-progress update + job-row
  update + `db.close()` in `finally`.
- Delete `process_document` (the flat fallback is now a strategy swap
  inside the subdocument strategy).
- Keep `_strip_section_images`, `get_processing_status` re-export.

**Verify:** `wc -l tasks.py` < 200; `grep -c "db\.\(add\|query\|commit\|flush\)" tasks.py` == 0.

---

## Slice 3 — Maintenance-tail uses strategy methods

### Step 3.1: `_run_maintenance` step calls strategy methods
- Replace `_run_ingestion_maintenance_tail`'s `if strategy.rebuild_aggregate_indexes:`
  branch with `ctx.ingestion.rebuild_aggregates(ctx)`; the
  mark-stale-when-skipped behaviour moves into the Fast/Indexed
  strategies' `rebuild_aggregates` (they mark stale instead of
  rebuilding). This is the completion of P1.
- `update_collection_summary` step similarly calls
  `ctx.ingestion.update_collection_summary(ctx)` unconditionally.

**Common mistake:** the Fast/Indexed "mark stale" path must still call
`maintenance_state.increment_uploads` — move that into the strategy's
`rebuild_aggregates` no-op body so it isn't lost.

---

## Slice 4 — Tests

### Step 4.1: Step-level unit tests
**File:** `tests/test_application/test_upload_pipeline.py`.
- One test per step per mode, per the S4.1 verify table. Use the same
  in-memory SQLite + `FakeEmbedder` + temp `DATA_DIR` fixtures as
  `test_upload_exactly_once.py`.

### Step 4.2: Regression test for exactly-once + per-mode outputs
- Extend `test_upload_exactly_once.py` with a parametrized case per
  ingestion mode asserting chunk count + index-file count.

---

## Common mistakes to watch for
- **Fallback ordering:** the subdocument strategy must validate
  *before* creating any `SubDocument` rows, or a fallback leaves
  orphaned rows.
- **Progress payload:** clients consume `progress`/`stage`/`message`
  strings — preserve the existing stage names (`parsing_breadcrumbs`,
  `processing_subdocuments`, `saving_chunks`, …) exactly or polling
  clients mis-render.
- **`processing_status` sharing:** the background thread and the request
  thread share the dict via the injected `ProgressStore` — confirmed
  safe (GIL + whole-value replaces). Do NOT introduce locking here.
- **`finally: db.close()`:** keep it in the thin `tasks.py` adapter, not
  in the pipeline (the pipeline must not own session lifecycle — it
  receives the session).
