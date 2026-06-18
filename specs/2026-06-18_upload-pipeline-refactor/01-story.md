# Upload Pipeline Refactor

## User Story
As a maintainer of kapsula, I want the two ~650-line `process_document*`
God Methods in `tasks.py` decomposed into a testable pipeline with
polymorphic ingestion strategies, so that adding an upload step or a new
ingestion mode no longer requires editing two near-parallel functions and
so `tasks.py` drops below the 500-line file limit.

## Context

`kapsula/presentation/api/tasks.py` (881 lines) contains two free
functions that do almost all upload work:

- `process_document(...)` (~180 lines) — the flat-document fallback.
- `process_document_with_subdocuments(...)` (~400 lines) — the Russian
  Doll path, which falls back to the flat path when no sub-documents are
  found.

Both interleave: progress updates, DB queries, structure extraction,
chunking, citation linking, chunk/card persistence, sub-document
indexing, aggregate rebuild, and stale-state marking. They share the
same skeleton but differ in the **chunking + persistence** step. They
also branch 4× on `ingestion_strategy.<flag>` booleans
(`build_document_indexes`, `update_collection_summary`,
`rebuild_aggregate_indexes`) — the exact case the **Strategy** pattern
exists to eliminate.

The maintenance-tail duplication was already extracted
(`_run_ingestion_maintenance_tail`), but the remaining body is still two
God Methods exceeding the 50-line method / 150-line class / 500-line
file limits by a wide margin. There are **no unit tests** on either
function (only an end-to-end "exactly once dispatch" test), because
their shape makes them untestable in isolation.

This refactor is the prerequisite for SC1 (file size) and the completion
of P1 (real strategies) and P3 (pipeline decomposition).

## Pattern decision

Walked the 21-pattern decision tree (AGENTS.md §2). The applicable
patterns, in priority order:

1. **Pipeline / Extract Method** (Q8) — the two functions exceed 50
   lines by ~5–8×. Decompose into named, single-responsibility steps.
2. **Template Method** (Q6) — the two functions share one skeleton
   (extract → chunk → persist → index → finalize → maintain); only the
   chunking+persistence step varies. Define the skeleton once.
3. **Strategy** (Q4) — behaviour varies by ingestion mode
   (`fast`/`indexed`/`full`) across three boolean switches. Replace the
   `if strategy.flag:` branches with polymorphic method calls. The
   flat-vs-subdocument chunking choice is *also* a Strategy selection at
   runtime (the subdocument path falls back to flat when
   `validate_subdocuments` is false).
4. **DI** (Q2, always) — the pipeline receives its chunker, embedder,
   progress store, maintenance-state manager, and repositories via the
   constructor; constructed in `startup/`.

**Rejected alternatives:**
- *Command per step* (each step a `PipelineStep` object with `run(ctx)`)
  — over-engineering for now. Template Method + private step methods is
  sufficient. Revisit if steps must be user-configurable/reordered.
- *Subclassing for flat vs subdocument* — the variant is one step, not a
  whole class hierarchy. A `ChunkingStrategy` injected into one pipeline
  is lighter.

## Non-Goals
- Changing the chunker algorithm, citation linker, or index builder.
- Changing the public MCP/HTTP contract or the on-disk index format.
- Changing the progress-reporting payload shape consumed by clients.
- Moving the dispatch mechanism (FastAPI `BackgroundTasks` for HTTP,
  `ThreadPoolBackgroundProcessor` for MCP — already settled by the
  `wire-upload-usecase` spec and the L1 fix).
- Persistence-layer changes (repositories already extracted).

## Slices
- **Slice 1** — Define `UploadPipelineContext` + `ChunkingStrategy` +
  retyped `UploadIngestionStrategy` (interface only, no behaviour move).
- **Slice 2** — Extract `UploadPipeline` (Template Method) consuming the
  strategies; move the shared skeleton out of `tasks.py`.
- **Slice 3** — Move the flat + subdocument chunking bodies into the two
  `ChunkingStrategy` implementations; delete the duplicated persistence
  logic.
- **Slice 4** — Make `tasks.py` a thin adapter; add unit tests per step.
