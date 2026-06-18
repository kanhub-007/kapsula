# Domain Model — Comprehensive Code-Review Fixes

This refactor introduces several new DTOs, interfaces, and read-models.
No existing domain entity changes shape.

## New read-models (application DTOs)

| DTO | Fields | Replaces | Lives in |
|-----|--------|----------|----------|
| `SubDocumentRead` | `id: int`, `breadcrumb_key: str`, `page_count: int`, `faiss_index_path: str \| None`, `bm25_index_path: str \| None` | ORM `SubDocument` returned from `SearchDataAccess` | `core/application/dto/sub_document_read.py` |
| `CollectionRead` | `id: int`, `name: str`, `account_id: int \| None`, `collection_id: str` | ORM `Collection` returned from `SearchDataAccess` | `core/application/dto/collection_read.py` |
| `DocumentRead` | `id: int`, `filename: str`, `faiss_index_path: str \| None`, `bm25_index_path: str \| None`, `collection_id: int` | ORM `Document` returned from `SearchDataAccess` | `core/application/dto/document_read.py` |
| `SearchHit` | `index: int`, `content: str`, `score: float`, `dense_score: float`, `sparse_score: float`, `rerank_score: float \| None`, `sub_document_id: int \| None`, `sub_document_key: str \| None`, `collection_id: int \| None`, `collection_name: str \| None`, `document_id: int \| None`, `document_filename: str \| None`, `expanded_content: str \| None`, plus route-confidence floats | `dict[str, Any]` returned from `MultiIndexSearcher.search_*` | `core/application/dto/search_hit.py` |
| `SubAnswer` | `question: str`, `answer: str`, `has_answer: bool`, `num_results: int`, `search_results: list[SearchHit]` | untyped sub-answer dict | `core/application/dto/sub_answer.py` |
| `SearchPlan` | `strategy: str`, `queries: list[str]`, `reasoning: str`, `total_unique_results: int \| None`, `sub_answers_count: int \| None` | untyped plan dict | `core/application/dto/search_plan.py` |
| `IntelligentSearchResult` | `answer: str \| None`, `has_answer: bool`, `relevant_results: list[int]`, `total_evaluated: int`, `search_results: list[SearchHit]`, `plan: SearchPlan \| None`, `sub_answers: list[SubAnswer] \| None`, `error: str \| None` | `dict[str, Any]` returned from `IntelligentSearcher` | `core/application/dto/intelligent_search_result.py` |
| `SearchPreparation` | `plan: SearchPlan \| None`, `collections: list[CollectionRead]`, `routed_collection: CollectionRead \| None`, `document_structure: list[dict]` | 4-tuple returns from `_prepare_intelligent_search` | `core/application/dto/search_preparation.py` |

## New / changed interfaces

| Interface | Methods | Implemented by | Notes |
|-----------|---------|----------------|-------|
| `SearchDataAccess` (retyped) | returns read-models; `get_account_by_name`/`save_account` removed | `SqlSearchDataAccess` | Closes A1, S1 |
| `ConsolidationCardRepository` | `fetch_extractive_cards(collection_id)`, `fetch_existing_topic_labels(collection_id)`, `upsert_topic_card(...)`, `add_card_references(...)`, `store_contradictions(...)`, `upsert_evolution_card(...)`, `add_gap_cards(...)`, `fetch_search_misses(...)`, `fetch_previous_run(...)`, `record_run(...)` | `SqlConsolidationCardRepository` | Closes A2, S4 |
| `MaintenanceStateRepository` (wraps current `MaintenanceStateManager`) | `mark_stale`, `mark_fresh`, `mark_consolidated`, `increment_uploads`, `list_stale` | `JsonMaintenanceStateRepository` (file-backed, in-memory cached) | Closes A3, PE1 |
| `ProgressStore` (Protocol, already satisfied by `UploadProgressTracker`) | `set`, `get`, `register_job` | `UploadProgressTracker` over `processing_status` | Closes A4 |

## New interfaces for upload pipeline (P1)

| Interface | Methods |
|-----------|---------|
| `UploadIngestionStrategy` (retyped) | `mode: str`, `build_indexes(ctx) -> None`, `run_collection_maintenance(ctx) -> None`, `finalize(ctx) -> None` |

The `UploadPipelineContext` carries `db`, `document`, `chunks`,
`parent_sections`, `subdocs`, `embedder`, `progress`,
`maintenance_state`, `start_time`, `job_id`, `ingestion_mode`.

## Fusion Template Method (P4)

| Class | Role |
|-------|------|
| `BaseFusion` | `fuse()` skeleton: build map, score via abstract hooks, sort, quality-filter |
| `RRFFusion(BaseFusion)` | overrides `_dense_score`, `_sparse_score` |
| `WeightedFusion(BaseFusion)` | overrides `_dense_score`, `_sparse_score` |

## Restricted unpickler (SE2)

| Class | Purpose |
|-------|---------|
| `_Bm25Unpickler(pickle.Unpickler)` | overrides `find_class` to allow only `rank_bm25.BM25Plus`, `rank_bm25.BM25Okapi`, and built-in container types |

## Entity vs ORM separation

Unchanged. All new DTOs are pure dataclasses in `core/application/dto/`.
Mappers for the new read-models live in `infrastructure/repositories/data/mappers.py`.

## Architecture decisions

- **A1** — read-models are application DTOs (not domain entities) because
  they exist only to cross the application→presentation boundary for
  search queries; they carry no domain behaviour.
- **A2** — `ConsolidationCardRepository` is a write repository (domain
  interface) because consolidation mutates persistent state.
- **A3** — `MaintenanceStateManager` keeps its current JSON-file backing
  store (wrapped as `JsonMaintenanceStateRepository`) to avoid a schema
  migration in this slice; the DB move is deferred.
- **L1** — the API route keeps FastAPI `BackgroundTasks` as the single
  dispatch point; the use case is wired with a `NoOpBackgroundProcessor`
  for the API factory and a real `ThreadPoolBackgroundProcessor` for the
  MCP factory. This matches the `wire-upload-usecase` spec's decision.
