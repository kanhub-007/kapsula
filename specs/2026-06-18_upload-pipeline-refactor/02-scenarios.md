# Scenarios — Upload Pipeline Refactor

Ordered by MoSCoW within each slice. Each scenario closes the noted
finding IDs.

---

## Slice 1 — Strategy + context interfaces (no behaviour move yet)

### Scenario S1.1: `UploadIngestionStrategy` carries behaviour, not flags
**Priority:** Must
**Closes:** P1

**Gherkin:**
  Given `FastUploadIngestionStrategy`, `IndexedUploadIngestionStrategy`, `FullUploadIngestionStrategy`
  When  the pipeline runs
  Then  each strategy implements `build_indexes(ctx)`, `update_collection_summary(ctx)`, `rebuild_aggregates(ctx)`
  And   no caller branches on `strategy.build_document_indexes` / `.update_collection_summary` / `.rebuild_aggregate_indexes`

**Verify:** `grep "ingestion_strategy\.\(build_document_indexes\|update_collection_summary\|rebuild_aggregate_indexes\)" kapsula/` returns nothing.

### Scenario S1.2: `UploadPipelineContext` carries every dependency + intermediate
**Priority:** Must

**Gherkin:**
  Given an upload in flight
  When  a step runs
  Then  it reads inputs/outputs from a single `UploadPipelineContext` (db, document, chunks, parent_sections, subdocs, embedder, progress, maintenance_state, job_id, ingestion_mode, start_time)
  And   no step takes >6 positional parameters (no long-parameter-list smell)

---

## Slice 2 — Template Method pipeline skeleton

### Scenario S2.1: One skeleton orchestrates both upload shapes
**Priority:** Must
**Closes:** P3, SC1 (file size)

**Gherkin:**
  Given `UploadPipeline.run(ctx)`
  When  invoked
  Then  it executes named steps in order: `extract_structure` → `chunk_and_persist` → `build_indexes` → `finalize_document` → `run_maintenance`
  And   `run()` is <30 lines (dispatcher only)
  And   each step method is <50 lines

**Verify:** `UploadPipeline.run` source is a flat list of `self._<step>(ctx)` calls; each step method ≤ 50 lines.

### Scenario S2.2: `tasks.py` becomes a thin adapter
**Priority:** Must
**Closes:** SC1

**Gherkin:**
  Given the refactor is complete
  When  `wc -l kapsula/presentation/api/tasks.py`
  Then  the file is < 200 lines (only: dispatch wrappers, `_strip_section_images`, `get_processing_status` re-export, the thin `process_document_with_subdocuments` that builds a pipeline + calls `.run()`)
  And   `tasks.py` contains zero `db.add` / `db.query` / `db.commit` calls (all moved to steps/repos)

**Verify:** `grep -c "db\.\(add\|query\|commit\|flush\)" tasks.py` == 0.

### Scenario S2.3: Fallback from subdocument to flat is a strategy swap
**Priority:** Must

**Gherkin:**
  Given `process_document_with_subdocuments` extracts subdocuments
  When  `validate_subdocuments(subdocs)` is false
  Then  the pipeline swaps its `ChunkingStrategy` to the flat variant and continues (no separate `process_document` code path)
  And   exactly one skeleton runs in either case

---

## Slice 3 — Chunking strategies + persistence dedup

### Scenario S3.1: Flat and subdocument chunking share persistence
**Priority:** Must
**Closes:** DRY between the two functions

**Gherkin:**
  Given chunks produced by either `ChunkingStrategy`
  When  they are persisted
  Then  both paths call the same `ChunkPersistenceStep` (one implementation of `_persist_chunks` / `_link_and_persist_subdoc_chunks` / library-card creation)
  And   library-card + chunk-metadata construction is not duplicated

**Verify:** diff of the two strategy files shows no shared persistence code.

### Scenario S3.2: Maintenance tail uses the strategy methods
**Priority:** Should

**Gherkin:**
  Given the maintenance step
  When  it runs
  Then  it calls `strategy.update_collection_summary(ctx)` and `strategy.rebuild_aggregates(ctx)` (no `if` on flags)
  And   the Fast strategy's methods are no-ops; Full's do the work; Indexed's rebuild-aggregates is a no-op but summary is too

---

## Slice 4 — Tests (T1.5 expansion)

### Scenario S4.1: Each pipeline step is unit-testable in isolation
**Priority:** Must
**Closes:** the remaining test gap on the upload path

**Verify (Classical, fakes at boundaries):** for each step, a test with
an in-memory SQLite + `FakeEmbedder` + temp `DATA_DIR`:
- `extract_structure` → writes one `DocumentStructure` row.
- `chunk_and_persist` (flat) → chunk rows == chunker output length.
- `chunk_and_persist` (subdocument) → one `SubDocument` per breadcrumb + chunks linked.
- `build_indexes` (indexed/full) → exactly one FAISS + one BM25 file per document/subdocument.
- `build_indexes` (fast) → zero index files.
- `run_maintenance` (full) → aggregate rebuilt; (fast/indexed) → state marked stale, no rebuild.

### Scenario S4.2: End-to-end pipeline preserves exactly-once dispatch
**Priority:** Must
**Closes:** regression guard for the L1 fix

**Verify:** existing `test_upload_exactly_once.py` stays green; add a
variant asserting chunk count and index-file count for each ingestion mode.

---

## Cross-cutting verify (every slice)
- `.venv/Scripts/python.exe -m pytest tests/ -q` → all green (the
  HF-network test excepted).
- `ruff check kapsula/ tests/` → 0 errors.
- `black --check kapsula/ tests/` → clean.
- `wc -l kapsula/presentation/api/tasks.py` → < 200.
