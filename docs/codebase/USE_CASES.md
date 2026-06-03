# Use Cases

Application-layer orchestration. Location: `kapsula/core/application/use_cases/`

## DeleteDocumentUseCase

**File:** `use_cases/delete_document.py`

Orchestrates soft-deletion of a document:
1. Delete index files from disk (via `IndexManager`)
2. Invalidate aggregate caches
3. Cascade-delete related DB records (via `DocumentRepository`)
4. Mark document as archived
5. Rebuild collection + account aggregate indexes

**Dependencies (all interfaces):**
- `IndexManager` — file I/O for index lifecycle
- `DocumentRepository` — DB persistence

**Returns:** `DeleteDocumentResult` (DTO from `dto/delete_document_result.py`)

## UploadDocumentUseCase

**File:** `use_cases/upload_document.py`

Validates and persists a new markdown document:
1. Validate file path + extension + collection existence
2. Create domain `Document` entity
3. Persist via `DocumentRepository`
4. Register progress tracking via `ProgressTracker`
5. Start background processing via `BackgroundProcessor`

**Dependencies (all interfaces):**
- `BackgroundProcessor` — starts background chunking/indexing
- `DocumentRepository` — DB persistence
- `ProgressTracker` — job lifecycle tracking

**Returns:** `UploadDocumentResult` (DTO from `dto/upload_document_result.py`)

## Other Use Cases (pre-existing)

| Use Case | File | Purpose |
|----------|------|---------|
| `HybridSearcher` | `hybrid_searcher.py` | Dense + sparse retrieval → fusion → rerank |
| `MultiIndexSearcher` | `multi_index_searcher.py` | Multi-document/collection aggregation |
| `IntelligentSearcher` | `intelligent_searcher.py` | Query planning → sub-searches → answer |
| `QueryPlanner` | `planning/query_planner.py` | LLM-driven query decomposition |
| `CollectionSummaryGenerator` | `collection_summary.py` | LLM summary maintenance |
| `ContextExpansion` | `context_expansion.py` | Library Card-based chunk expansion |
| `ConsolidationRunner` | `repositories/processing/consolidation_runner.py` | Topic clustering, contradiction detection, gap analysis |

## Design Notes

- Use cases depend on **domain interfaces** (ABCs), never concrete implementations.
- Dependencies are injected via constructor (Dependency Inversion).
- Factory functions in `startup/__init__.py` wire concrete implementations.
- Use cases return **DTOs** (data classes) — callers never receive domain entities directly unless they're immutable values.
