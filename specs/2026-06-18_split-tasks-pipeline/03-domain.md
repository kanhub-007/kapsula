# Domain Model — Split tasks.py Pipeline

## New Interfaces

### PipelineStage (Protocol)
```python
class PipelineStage(Protocol):
    """A single stage in the document processing pipeline."""
    name: str  # Display name for progress tracking, e.g. "extracting_structure"

    def run(self, job_id: str, content: str, max_tokens: int, db: Any) -> None:
        """Execute this stage. Raises on failure."""
        ...
```

## New Entities / Value Objects

None. This refactoring extracts existing logic into modules; no new domain entities are created.

## Modified Interfaces

None. All domain interfaces (`Embedder`, `Chunker`, `BackgroundProcessor`, etc.) are unchanged.

## Entity vs ORM Separation

No new ORM models. The `PersistenceStage` uses existing ORM tables:
- `Chunk` (infrastructure/data/tables/chunk.py)
- `LibraryCard` (infrastructure/data/tables/library_card.py)
- `SubDocument` (infrastructure/data/tables/sub_document.py)
- `SubDocumentPage` (infrastructure/data/tables/sub_document_page.py)
- `DocumentStructure` (infrastructure/data/tables/document_structure.py)
- `Document` (infrastructure/data/tables/document.py)

The `processing_status` dict (mutable module-level state in `tasks.py`) is wrapped by `UploadProgressTracker` (already exists in `presentation/upload/upload_progress_tracker.py`).

## Stage Module Dependency Map

```
structure_extractor  → chunking/markdown_chunker (infra)
parent_extractor     → chunking (infra)
citation_linker      → citation_matching (domain), header_matcher (infra)
chunk_pipeline       → MarkdownChunker (infra)
persistence_stage    → ORM tables (infra), Session
index_build_stage    → Embedder (domain), DocumentIndexBuilder (infra)
aggregate_build_stage → AggregateIndexBuilder (infra), MaintenanceStateManager (presentation)
collection_summary_stage → CollectionSummaryGenerator (app), ChatClient (domain)
```

No stage imports another stage. All dependencies flow through constructor injection.
