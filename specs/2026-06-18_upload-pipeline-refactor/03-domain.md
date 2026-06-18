# Domain Model — Upload Pipeline Refactor

No new persisted entities. Introduces one context dataclass, one
strategy interface, and one orchestrator class — all in the application
layer.

## New types

### `UploadPipelineContext` (application DTO, mutable carrier)
Carries every dependency and intermediate result so step methods have
≤6 parameters (closes the long-parameter-list smell).

| Field | Type | Purpose |
|-------|------|---------|
| `db` | `Session` | DB session for the run |
| `document` | `Document` (domain) | The document being processed |
| `job_id` | `str` | GUID |
| `ingestion_mode` | `str` | normalized mode |
| `start_time` | `float` | perf marker |
| `markdown_content` | `str` | raw input |
| `chunker` | `Chunker` | injected |
| `embedder` | `Embedder` | injected |
| `progress` | `ProgressStore` | injected (replaces module-global `_upload_progress`) |
| `maintenance_state` | `MaintenanceStateManager` | injected |
| `card_repo` / `chunk_repo` | repositories | injected |
| `structure` | `str \| None` | skeleton (set by `extract_structure`) |
| `parent_sections` | `dict` | set by chunking step |
| `chunks` | `list[dict]` | set by chunking step |
| `subdocs` | `list[SubDocument] \| None` | set by subdocument chunking |
| `duration` | `float \| None` | set by `finalize_document` |

Lives in `core/application/dto/upload_pipeline_context.py`.

### `UploadIngestionStrategy` (retyped Protocol → real methods)
| Method | Fast | Indexed | Full |
|--------|------|---------|------|
| `mode` | `"fast"` | `"indexed"` | `"full"` |
| `build_indexes(ctx)` | no-op | builds doc + subdoc indexes | same as indexed |
| `update_collection_summary(ctx)` | no-op | no-op | regenerates collection library card |
| `rebuild_aggregates(ctx)` | no-op | no-op | rebuilds collection + account aggregates |

The three existing frozen-dataclass files gain these methods (Fast =
all no-ops; Indexed = only `build_indexes`; Full = all three). The
boolean flags are removed.

### `ChunkingStrategy` (new Strategy)
| Method | Returns |
|--------|---------|
| `extract_and_chunk(ctx) -> None` | populates `ctx.chunks`, `ctx.parent_sections`, `ctx.subdocs` (if any) on the context |

Implementations:
- `FlatChunkingStrategy` — chunks `markdown_content` as one document.
- `SubDocumentChunkingStrategy` — splits on breadcrumbs, chunks each
  subdocument, falls back to Flat when `validate_subdocuments` is false
  (composition: holds a `FlatChunkingStrategy` for the fallback).

### `UploadPipeline` (Template Method orchestrator)
```python
class UploadPipeline:
    def __init__(self, chunking: ChunkingStrategy, ingestion: UploadIngestionStrategy): ...
    def run(self, ctx: UploadPipelineContext) -> None:
        self._extract_structure(ctx)
        self._chunk_and_persist(ctx)          # delegates to chunking strategy
        self._build_indexes(ctx)              # delegates to ingestion strategy
        self._finalize_document(ctx)
        self._run_maintenance(ctx)            # delegates to ingestion strategy
```
Each `_step` is a private method <50 lines. `run()` is a flat
dispatcher <30 lines.

Lives in `core/application/use_cases/upload/upload_pipeline.py`.

## Entity vs ORM separation
Unchanged. Steps use existing repositories (`SqlDocumentRepository`,
`SqlChunkRepository`, etc.) and mappers. No new ORM tables.

## Interfaces (for DI)
| Interface | Already exists? | Used by |
|-----------|-----------------|---------|
| `Chunker` | yes | pipeline (chunking strategies) |
| `Embedder` | yes | pipeline (index step) |
| `ProgressStore` | yes (`ProgressTracker`/`UploadProgressTracker`) | pipeline (every step) |
| `MaintenanceStateManager` | yes (concrete; wrap in Protocol if needed) | maintenance step |
| `UploadIngestionStrategy` | retyped here | maintenance step |
| `ChunkingStrategy` | new here | chunk step |

## Architecture decision
The pipeline lives in `core/application/use_cases/upload/` (orchestration,
depends only on domain interfaces + DTOs). `tasks.py` (presentation)
becomes a ~50-line adapter that builds a context + pipeline via
`startup/create_upload_pipeline()` and calls `.run()`. This preserves
the layer rule: the pipeline never imports presentation; `tasks.py`
imports the pipeline.
