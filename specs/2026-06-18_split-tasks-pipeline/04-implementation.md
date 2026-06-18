# Implementation Guide — Split tasks.py Pipeline

> **Prerequisites:** Run `python -m pytest tests/ -v` before starting. Save the output as baseline.
> **Rollback:** If any step breaks, `git checkout kapsula/presentation/api/tasks.py` and re-run tests.

---

### Step 0: Define the PipelineStage Protocol
**File:** `kapsula/core/application/use_cases/processing/pipeline_stage.py` (new)
```python
from typing import Any, Protocol

class PipelineStage(Protocol):
    """A single stage in the document processing pipeline."""
    name: str
    def run(self, job_id: str, content: str, max_tokens: int, db: Any) -> None: ...
```
This is the contract every extracted stage must implement. The `name` attribute is used for progress tracking (maps to the `stage` field in `processing_status`).
**Verify:** `python -c "from kapsula.core.application.use_cases.processing.pipeline_stage import PipelineStage; print('OK')"`

---

### Step 1: Extract Citation Linker
**File:** `kapsula/infrastructure/repositories/processing/citation_linker.py`
Move `add_citation_metadata_to_chunks` from tasks.py. This is the cleanest extraction: no DB, only domain `citation_matching` + `header_matcher` (already in infra).
**Verify:** `python -c "from kapsula.infrastructure.repositories.processing.citation_linker import add_citation_metadata_to_chunks"`
**Common mistake:** Forgetting to update the `from kapsula.core.domain.citation_matching import find_chunk_in_markdown` import inside the function body.

---

### Step 2: Extract Persistence Stage
**File:** `kapsula/infrastructure/repositories/processing/persistence_stage.py`
Extract chunk saving, parent section saving, sub-document creation, and library card saving. Takes `db: Session` and returns persisted IDs. This stage wraps the noisy ORM loop code.
**Verify:** Unit test with in-memory SQLite.
**Common mistake:** DB session lifecycle — the stage should NOT commit; the orchestrator commits.

---

### Step 3: Extract Index Build Stage
**File:** `kapsula/infrastructure/repositories/processing/index_build_stage.py`
Wrap `DocumentIndexBuilder.build()` call with env-var resolution for embedder URL. Takes `Embedder`, `data_dir`, returns `IndexPaths`.
**Verify:** Integration test with temp FAISS files.
**Common mistake:** The `SubDocumentBatchIndexer` is already extracted in `presentation/upload/` — coordinate with it.

---

### Step 4: Extract Aggregate Build Stage
**File:** `kapsula/infrastructure/repositories/processing/aggregate_build_stage.py`
Wrap `_rebuild_collection_aggregate_index` from tasks.py. Takes `AggregateIndexBuilder`, collection, document.
**Verify:** Integration test with temp aggregate index files.
**Common mistake:** The `MaintenanceStateManager` is called conditionally — keep the conditional in the orchestrator, not the stage.

---

### Step 5: Extract Collection Summary Stage
**File:** `kapsula/infrastructure/repositories/processing/collection_summary_stage.py`
Wrap `update_collection_library_card` from tasks.py. Takes `CollectionSummaryGenerator`, `db`, `document_id`.
**Verify:** Unit test with fake ChatClient.
**Common mistake:** The function already handles missing cards gracefully; preserve that.

---

### Step 6: Define Pipeline Orchestrator
**File:** `kapsula/presentation/api/tasks.py` (refactored to ~50 lines)

Replace the entire file contents with an orchestrator + the `processing_status` dict (which MUST stay module-level because `get_processing_status()` in `routes/documents.py` reads it directly):

```python
"""Background task orchestration — thin wrapper around processing stages."""

import logging

from kapsula.presentation.upload.upload_progress_tracker import UploadProgressTracker
from kapsula.infrastructure.repositories.processing.persistence_stage import PersistenceStage
from kapsula.infrastructure.repositories.processing.index_build_stage import IndexBuildStage
# ... other stage imports

logger = logging.getLogger(__name__)

# Module-level dict — kept here because get_processing_status() reads it directly.
# Do NOT move this. Stages access it through UploadProgressTracker only.
processing_status = {}

_upload_progress = UploadProgressTracker(processing_status, logger)


class DocumentPipeline:
    """Orchestrates document processing stages in sequence."""

    def __init__(self, stages: list, progress: UploadProgressTracker):
        self._stages = stages
        self._progress = progress

    def execute(self, job_id: str, content: str, max_tokens: int, db) -> None:
        start_time = time.time()
        try:
            for stage in self._stages:
                self._progress.set(job_id, status="processing", stage=stage.name, ...)
                stage.run(job_id, content, max_tokens, db)
            # Mark completed
            document = db.query(Document).filter(Document.job_id == job_id).first()
            if document:
                document.status = "completed"
                document.duration = time.time() - start_time
                db.commit()
            self._progress.set(job_id, status="completed", progress=100, stage="completed", ...)
        except Exception as e:
            logger.error("Pipeline failed for %s: %s", job_id, e, exc_info=True)
            document = db.query(Document).filter(Document.job_id == job_id).first()
            if document:
                document.status = "failed"
                db.commit()
            self._progress.set(job_id, status="failed", progress=0, stage="failed", ...)
        finally:
            db.close()


def process_document(job_id, markdown_content, max_tokens, db, ingestion_mode="indexed"):
    """Legacy entry point — delegates to DocumentPipeline."""
    import os
    from kapsula.infrastructure.repositories.embedding.huggingface_embedder import HuggingFaceEmbedder
    from kapsula.infrastructure.repositories.indexing import DocumentIndexBuilder
    from kapsula.infrastructure.data.connection import DATA_DIR
    from kapsula.core.application.use_cases.upload.upload_ingestion_strategy_factory import UploadIngestionStrategyFactory

    strategy = UploadIngestionStrategyFactory.create(ingestion_mode)
    embedder = HuggingFaceEmbedder(
        endpoint_url=os.getenv("EMBEDDING_MODEL_URL", "Qwen/Qwen3-Embedding-8B"),
        token=os.getenv("HF_API_TOKEN") or os.getenv("HF_TOKEN", ""),
    )

    stages: list = [
        StructureExtractionStage(),
        ParentExtractionStage(),
        ChunkingStage(max_tokens),
        CitationLinkerStage(),
        PersistenceStage(),
    ]
    if strategy.build_document_indexes:
        stages.append(IndexBuildStage(embedder, DocumentIndexBuilder(embedder, DATA_DIR)))
    if strategy.rebuild_aggregate_indexes:
        stages.append(AggregateBuildStage(embedder, DATA_DIR))
    if strategy.update_collection_summary:
        stages.append(CollectionSummaryStage())

    pipeline = DocumentPipeline(stages, _upload_progress)
    pipeline.execute(job_id, markdown_content, max_tokens, db)


def process_document_with_subdocuments(job_id, markdown_content, max_tokens, db, ingestion_mode="indexed"):
    """Legacy entry point for sub-document path — delegates to SubDocumentPipeline."""
    # Same pattern as above, but uses SubDocumentPipeline which wraps the
    # existing SubDocumentBatchIndexer and adds sub-doc creation stages.
    # Full implementation extracted from current tasks.py lines ~470-950.
    ...

def get_processing_status(job_id: str) -> dict | None:
    """Return current processing status for a job. Used by progress route."""
    return processing_status.get(job_id)
```

**Critical — preserve exact progress percentages:** The old code used specific values:
- 5: parsing_breadcrumbs
- 10: extracting_structure / processing_subdocuments
- 20: extracting_parents
- 30: chunking
- 60: saving_chunks
- 65: saving_parents
- 70: linking_chunks
- 83: document_card
- 85: building_indexes
- 86: collection_summary
- 98: finalizing
- 100: completed

Each stage must set the SAME progress value as before. The `UploadProgressTracker.set()` call in each stage's `run()` method must include the correct progress number.

**Verify:** Run full upload integration test — document completes with "completed" status.
**Common mistake:** Using different progress values than the original code. The route `GET /documents/progress/{job_id}` is the external contract — progress values must match.

---

### Step 7: Add Deprecation Re-exports
**File:** `kapsula/presentation/api/tasks.py` (bottom)
```python
import warnings
def process_document(*args, **kwargs):
    warnings.warn("process_document is deprecated. Use DocumentPipeline.", DeprecationWarning)
    return _legacy_process_document(*args, **kwargs)
```
**Verify:** `python -c "from kapsula.presentation.api.tasks import process_document; print('OK')"` emits deprecation warning but succeeds.

---

### Step 8: Update All Call Sites
- `presentation/api/routes/documents.py` — switch to `DocumentPipeline`
- `presentation/upload/upload_job_manager.py` — no change needed (uses progress tracker)
- Any test files importing tasks.py — update imports

**Verify:** Run full test suite: `pytest tests/`
**Common mistake:** The `processing_status` module-level dict is used by `get_processing_status()` — ensure it's still populated by the pipeline.
