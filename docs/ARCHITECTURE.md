# Architecture

Kapsula follows **Clean Architecture** with a clear separation between domain logic, application use cases, infrastructure, and presentation.

---

## Layer Map

```
┌──────────────────────────────────────────────────┐
│  presentation/   FastAPI routes, MCP tools        │  ← HTTP, stdio
├──────────────────────────────────────────────────┤
│  startup/        Composition root, DI wiring      │  ← app factories
├──────────────────────────────────────────────────┤
│  core/application/   Use cases, DTOs, planning    │  ← orchestration
├──────────────────────────────────────────────────┤
│  core/domain/        Entities, interfaces, fusion │  ← pure logic
├──────────────────────────────────────────────────┤
│  infrastructure/     FAISS, BM25, embeddings, SQL │  ← I/O
└──────────────────────────────────────────────────┘
```

### `core/domain/` — Pure Business Logic

No framework dependencies. Defines:
- **Entities** — `Account`, `Collection`, `Document`, `SubDocument`, `SubDocumentPage`, `Chunk`, `LibraryCard`, `DocumentStructure` (pure dataclasses)
- **Interfaces** — `Embedder`, `Reranker`, `Retriever`, `Fusion`, `Chunker`, `ElementHandler`, `ChatClient`, `SearchDataAccess`, `IndexManager`, `BackgroundProcessor`, `DocumentRepository`, `AccountRepository`, `CollectionRepository`, `ProgressTracker`, `ChunkRepository`, `SubDocumentRepository`, `LibraryCardRepository`
- **Fusion algorithms** — `WeightedFusion`, `RRFFusion`
- **Quality filter** — `passes_quality_filter()`
- **Text processing** — `tokenize()`, `simple_stem()`, `is_meaningful_chunk()`
- **Citation matching** — `strip_inline_formatting()`, `find_chunk_in_markdown()`

### `core/application/` — Use Cases

Orchestrates domain objects via interfaces:
- `DeleteDocumentUseCase` — soft-delete → cascade cleanup → index rebuild
- `UploadDocumentUseCase` — validate → persist → start background processing
- `HybridSearcher` — Dense + sparse retrieval → fusion → rerank
- `MultiIndexSearcher` — Multi-document/collection aggregation with LLM routing
- `IntelligentSearcher` — Query planning → parallel sub-searches → answer synthesis
- `QueryPlanner` — LLM-driven query decomposition
- `CollectionSummaryGenerator` — LLM summary maintenance
- `ContextExpansion` — Library Card-based chunk expansion
- `ResultFilter` — Node-type filtering (text/table/code)
- **Selectors** — `CollectionSelector`, `SubDocumentSelector` (LLM routing)
- **DTOs** — `CollectionSearch`, `DeleteDocumentResult`, `UploadDocumentResult`, `RebuildResult`, etc.

### `infrastructure/` — Concrete Implementations

- **`data/`** — ORM tables, `mappers.py` (domain↔ORM), SQL repositories (`SqlAccountRepository`, `SqlCollectionRepository`, `SqlDocumentRepository`, `SqlChunkRepository`, `SqlLibraryCardRepository`), `SqlSearchDataAccess`
- **`repositories/retrieval/`** — `DenseRetriever` (FAISS), `SparseRetriever` (BM25Plus)
- **`repositories/indexing/`** — `DocumentIndexBuilder`, `AggregateIndexBuilder`, `FileSystemIndexManager`
- **`repositories/embedding/`** — `HuggingFaceEmbedder` (Qwen3-Embedding-8B)
- **`repositories/reranking/`** — `LocalCrossEncoderReranker`, `HFEndpointReranker`
- **`repositories/chunking/`** — Markdown parser, chunk pipeline, element handlers
- **`repositories/processing/`** — `ThreadPoolBackgroundProcessor`, `InMemoryProgressTracker`
- **`external/llm/`** — `HuggingFaceChatClient` (DeepSeek-V3.2-Exp)

### `presentation/` — Adapters

- **`api/`** — FastAPI routes (`accounts`, `collections`, `documents`, `search`), Pydantic models, background tasks
- **`mcp/`** — FastMCP server, tools split by domain (`accounts`, `collections`, `documents`, `export`, `search`)

### `startup/` — Composition Root

- DI factory functions: `create_delete_document_use_case()`, `create_upload_document_use_case()`,
  `create_embedder()`, `create_chat_client()`, `create_reranker()`, etc.
- App bootstrapping: `bootstrap()`

### `startup/` — Composition Root

Wires everything together:
- `bootstrap()` — Database init + default account creation
- `create_embedder()`, `create_chat_client()`, `create_reranker()` — Singleton factories
- `create_multi_index_searcher()` — Wires retrievers, fusion, reranker, data access
- `api.py` — FastAPI `create_app()` with lifespan handler
- `mcp.py` — FastMCP `create_server()` with tool registration

---

## Database Schema

Eight SQLAlchemy models in a hierarchical relationship:

```
Account 1──N Collection 1──N Document 1──1 DocumentStructure
                                     1──N SubDocument 1──N SubDocumentPage
                                     1──N Chunk
                                     1──N LibraryCard
```

### `accounts`
| Column | Type | Notes |
|--------|------|-------|
| `id` | PK (int) | Auto-increment |
| `account_id` | GUID (str) | Public identifier, unique index |
| `name` | str | Human-readable |
| `created_at` | datetime | Auto |
| `ip_address` | str | Source tracking |

### `collections`
| Column | Type | Notes |
|--------|------|-------|
| `id` | PK (int) | |
| `collection_id` | GUID (str) | Public identifier |
| `account_id` | FK → accounts.id | |
| `name` | str | |
| `logo_filename` | str (nullable) | Collection branding |
| `created_at` | datetime | |
| `ip_address` | str | |

### `documents`
| Column | Type | Notes |
|--------|------|-------|
| `id` | PK (int) | |
| `job_id` | GUID (str) | Unique, used for progress tracking |
| `collection_id` | FK → collections.id | |
| `filename` | str | |
| `size` | int | File size in bytes |
| `content` | str | Full markdown text |
| `status` | str | `processing`, `completed`, `failed` |
| `faiss_index_path` | str (nullable) | Path to `.index` file |
| `bm25_index_path` | str (nullable) | Path to `.pkl` file |
| `duration` | float (nullable) | Processing time in seconds |
| `created_at` | datetime | |

### `sub_documents`
Created when markdown has breadcrumb-style H1s (e.g., `# domain / Docs / API`). Each gets independent FAISS/BM25 indexes.

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK (int) | |
| `document_id` | FK → documents.id | |
| `breadcrumb_key` | str | The grouping key (e.g., "API") |
| `breadcrumb_level` | int | Depth in breadcrumb path |
| `faiss_index_path` | str | |
| `bm25_index_path` | str | |
| `page_count` | int | Number of pages grouped here |
| `created_at` | datetime | |

### `sub_document_pages`
Individual pages within a sub-document.

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK (int) | |
| `sub_document_id` | FK → sub_documents.id | |
| `page_title` | str | |
| `breadcrumb_full` | str | Full breadcrumb path |
| `content_hash` | str | SHA256 for dedup |
| `created_at` | datetime | |

### `chunks`
Atomic search unit. One document has many chunks.

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK (int) | |
| `document_id` | FK → documents.id | |
| `sub_document_id` | FK (nullable) | For multi-index docs |
| `content` | str | Chunk text |
| `chunk_index` | int | Position within document |
| `token_count` | int | |
| `chunk_metadata` | JSON str | Header breadcrumb, node_type, parents hash, citation data |
| `created_at` | datetime | |

### `library_cards`
Context storage for Russian Doll expansion and consolidation.

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK (int) | |
| `collection_id` | FK → collections.id (nullable) | Set on creation for collection-scoped queries |
| `document_id` | FK → documents.id (nullable) | |
| `sub_document_id` | FK → sub_documents.id (nullable) | |
| `doc_id` | str (indexed) | SHA256 hash of section content |
| `level` | str | `level_1` (H3), `level_2` (H2), `level_3` (H1), `subdocument`, `document`, `collection` |
| `title` | str | Section heading |
| `content` | str | Full section text |
| `extra_metadata` | JSON str | Page titles, document summaries, contradiction details |
| `card_type` | str | `extractive` (from documents), `topic` (from consolidation), `evolution`, `gap` |
| `importance` | float | 0.0–1.0 relevance score (default 0.5) |
| `updated_at` | datetime (nullable) | Last consolidation update |
| `consolidation_run_id` | str (nullable) | Links to the consolidation run |
| `created_at` | datetime | |

### `document_structures`
1:1 with document. Skeleton of heading hierarchy.

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK (int) | |
| `document_id` | FK (unique) | |
| `skeleton_structure` | str | Markdown heading tree |
| `created_at` | datetime | |

### `consolidation_runs`
Tracks each consolidation execution.

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK (str) | UUID run identifier |
| `collection_id` | str | Collection GUID |
| `triggered_by` | str | `manual`, `auto`, or `upload` |
| `cards_created` | int | Topic cards generated |
| `cards_updated` | int | Topic cards updated |
| `conflicts_found` | int | Contradictions detected |
| `gaps_found` | int | Knowledge gaps identified |
| `error` | text (nullable) | Error message if run failed |
| `created_at` | datetime | |

### `upload_jobs`
Tracks document upload progress and metrics.

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK (int) | |
| `job_id` | str (unique, indexed) | Job GUID |
| `filename` | str | |
| `collection_id` | int (nullable) | |
| `collection_name` | str (nullable) | |
| `status` | str | `queued`, `processing`, `completed`, `failed` |
| `progress` | int | 0–100 |
| `stage` | str (nullable) | Current pipeline stage |
| `message` | text (nullable) | Human-readable status |
| `ingestion_mode` | str (nullable) | `fast`, `indexed`, or `full` |
| `chunk_count` | int (nullable) | |
| `subdocument_count` | int (nullable) | |
| `duration` | float (nullable) | Processing time in seconds |
| `error` | text (nullable) | |
| `created_at` | datetime | |
| `updated_at` | datetime | Auto-updated on status change |

### `search_miss_log`
Records low-result searches for gap detection.

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK (int) | |
| `collection_id` | str (nullable) | |
| `query` | text | The search query |
| `result_count` | int | Number of results returned |
| `top_score` | float (nullable) | Best score |
| `created_at` | datetime | |

### `card_references`
Links between library cards (source → target).

| Column | Type | Notes |
|--------|------|-------|
| `source_card_id` | FK → library_cards.id | |
| `target_card_id` | FK → library_cards.id | |
| `relation_type` | str | Relationship type |
| `created_at` | datetime | |

---

## Document Processing Pipeline

```
POST /documents/upload
  → Create Document record (status=processing)
  → Queue background task
     ├── Parse breadcrumbs → extract sub-documents
     ├── For each sub-document:
     │   ├── Extract parent sections (H1/H2/H3 with character spans)
     │   ├── Chunk markdown (type-aware, 512 token default)
     │   ├── Match chunks → parent sections (Library Cards)
     │   ├── Build FAISS + BM25 indexes
     │   └── Save chunks, library cards, sub-documents
     ├── Create document-level LibraryCard
     ├── Update collection LibraryCard (LLM summary)
     └── Mark status=completed
```

Progress tracked in-memory via `processing_status` dict. Poll with `GET /documents/progress/{job_id}`.

---

## Search Flow

```
Query
  → normalize
  → parallel: FAISS.search(k=50) │ BM25Plus.get_scores(k=50)
  → Fusion (RRF or weighted)
  → Quality filter (4 gates)
  → Node-type filter (optional: text/table/code)
  → Cross-encoder rerank (optional)
  → Context expansion via Library Cards (optional: narrow/deep)
  → Deduplicate by parent hash
  → Return top-k
```

For **intelligent search**: query planner decomposes into sub-questions → each runs hybrid search → LLM evaluates each → final synthesis.

For **multi-index search**: LLM routes to relevant sub-documents/collections → parallel search across selected indexes → global rerank → context expansion → top-k cutoff.

---

## Data Storage

```
data/
├── documents.db                    # SQLite database
├── indexes/                        # FAISS + BM25 indexes
│   └── {account_id}/
│       └── {collection_id}/
│           ├── {job_id}_faiss.index
│           ├── {job_id}_bm25.pkl
│           ├── {job_id}_subdoc_{id}_faiss.index
│           └── {job_id}_subdoc_{id}_bm25.pkl
├── logos/                          # Collection logo images
└── logs/                           # Application logs
```
