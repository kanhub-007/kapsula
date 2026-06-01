# Doc-Search

Hybrid document search engine — FAISS vector search + BM25 keyword retrieval with LLM-powered intelligent question answering, built on a **Russian Doll** hierarchical architecture.

---

## What It Does

- **Ingest** markdown documents, chunk them semantically (respecting code blocks, tables, lists, headings)
- **Index** with dual FAISS (dense vector) + BM25Plus (sparse keyword) indexes
- **Search** using hybrid fusion (RRF or weighted), cross-encoder reranking, and quality filtering
- **Answer** questions via LLM query planning and grounded answer generation
- **Expand** context using Library Cards — pull in parent sections around search hits
- **Serve** as a FastAPI REST API and/or an MCP server for AI assistant integration

---

## Why Hybrid? The Two Retrievers

Single-method search has a fundamental tradeoff. We solve it by running both and fusing intelligently.

### Dense Retrieval (FAISS)

Dense retrieval converts both the query and every document chunk into a **vector embedding** — a list of numbers representing its semantic meaning. Similarity is measured by how close vectors are in this high-dimensional space (cosine similarity via inner product).

**What it's great at:** finding conceptually related content even when different words are used. A query about "authentication" can find chunks about "login flow" or "credential verification" — concepts the system understands are related.

**Where it struggles:** exact keyword matching. A search for `API_KEY_HEADER_X` may miss results because the embedding model doesn't recognize it as a distinct technical term. It can also be "distracted" by semantically adjacent but irrelevant content.

### Sparse Retrieval (BM25Plus)

Sparse retrieval treats documents as bags of words and scores them by **term frequency and inverse document frequency** — rare words that appear often in a document get high weight. BM25Plus adds a delta constant to prevent negative scores on short documents.

**What it's great at:** exact keyword matching, technical terms, codes, specific names. A search for `API_KEY_HEADER_X` will precisely match chunks containing that string. It's deterministic and explainable.

**Where it struggles:** understanding concepts. A search for "how to handle errors" won't match chunks about "exception management" or "fault tolerance" because those words simply aren't there.

### Fusion: The Best of Both

By running both retrievers in parallel and fusing their results, we get:
- Semantic understanding from dense retrieval
- Precision from sparse retrieval
- Cross-validation — results both methods agree on are strong signals

---

## Fusion Strategies

After both retrievers return their top-50 results, we merge them using one of two strategies:

### Reciprocal Rank Fusion (RRF)

```
RRF_score = Σ 1 / (k + rank + 1)     where k = 60
```

Each result gets a contribution from its rank position in each retriever's list. A chunk ranked #1 in FAISS and #3 in BM25 gets `1/61 + 1/63 = 0.0323`.

**Why we use it:** RRF doesn't care about raw score magnitudes. FAISS returns similarity scores in 0–1 range while BM25 returns unbounded positive scores — they're incomparable. RRF sidesteps this entirely by using rank position, which is inherently comparable across methods.

**Best for:** queries where one retriever massively outperforms the other, or when score distributions are unreliable.

### Weighted Fusion

```
score = dense_weight × dense_score + sparse_weight × (sparse_score / max_sparse)
```

Dense and sparse scores are combined linearly after normalizing sparse scores against the maximum. Weights adapt dynamically based on query type:
- "What is X?" → 0.75 dense, 0.25 sparse (conceptual queries need semantics)
- "API_KEY_HEADER_X" → 0.40 dense, 0.60 sparse (specific terms need keyword precision)
- General queries → 0.70 dense, 0.30 sparse

**Why we use it:** when both retrievers produce meaningful score distributions, weighted fusion gives finer-grained control than RRF. The adaptive weighting means the system adjusts its "personality" to match the query.

### Quality Gates

After fusion (regardless of strategy), results must pass one of four quality gates:

| Gate | Condition | Meaning |
|------|-----------|---------|
| Both signals | dense > 0.15 **and** sparse_norm > 0.1 | Both methods found it |
| Strong dense | dense ≥ 0.55 **and** sparse_norm > 0.02 | Very strong semantic match, some keyword signal |
| Balanced | dense ≥ 0.4 **and** sparse_norm > 0.05 | Good signal from both |
| Strong sparse | sparse_norm ≥ 0.3 **and** dense ≥ 0.25 | Strong keyword match, some semantic signal |

Pure single-method results are discarded. This enforces that hybrid search requires **hybrid agreement** — a design principle that prevents either retriever from dominating results when its signal is unverified.

---

## The Russian Doll: How Library Cards Solve Context Collapse

### The Problem

Traditional chunk-based search has a fundamental flaw: when you split a document into small chunks, each chunk loses its surrounding context. A search hit on "the function requires three parameters" tells you there's a function — but not what function, what parameters, or why you'd call it.

Returning all chunks from a section solves this but overwhelms the user. Returning just the hit chunk is too narrow. Neither is right.

### Our Approach: Library Cards

During document ingestion, for every heading section (H1, H2, H3), we extract the **full section content** and store it as a Library Card — a database row containing the section title, all its text (including nested subsections), and a SHA256 hash for lookup.

Each chunk stores a **parent reference** in its metadata — a hash pointing to the H3 section it belongs to, the H2 chapter above it, and the H1 page above that.

### How It Works at Search Time

1. **Search returns a chunk** — a small fragment of text
2. **Look up the chunk's parent hash** from its metadata
3. **Replace the chunk content** with the full parent section from the Library Card
4. **Deduplicate** — multiple chunks from the same section collapse into one result

The key insight: **the parent section already contains the chunk**. By expanding to the parent, we give the user surrounding context *without* returning duplicate content. They see the chunk embedded in its natural context.

### Context Modes

| Mode | Expands To | Use Case |
|------|-----------|----------|
| `none` | Chunk only | Quick fact retrieval |
| `narrow` | H3 section (immediate parent) | Specific detail with surrounding paragraph |
| `deep` | H2 chapter | Broader topic understanding |

### Why This Matters

For LLM-powered search, this is transformative. The LLM receives full sections with complete context rather than isolated fragments. An answer about "how to configure the rate limiter" gets the full rate limiting section — examples, edge cases, configuration options — not just the one sentence that mentions "rate_limit_ms".

For user-facing search, it eliminates the "where am I?" disorientation. Each result is self-contained and readable.

Beyond search, Library Cards serve as a **hierarchical index** — they describe the structure of every document at H1, H2, and H3 levels. The query planner uses this structure to target sub-questions to specific sections, and the LLM router uses collection-level cards to route queries to the right collection.

---

## Pipeline Overview

```
Markdown → Chunking → FAISS + BM25 Indexes → Hybrid Search → Rerank → Context Expansion → Answer
```

| Stage | What Happens |
|-------|-------------|
| **Chunking** | `unstructured` parses markdown into typed elements. Chunks respect heading, table, code, and list boundaries. Breadcrumb H1s split documents into sub-documents. |
| **Indexing** | FAISS `IndexFlatIP` with Qwen3-Embedding-8B embeddings (dense). BM25Plus with simple stemming tokenizer (sparse). |
| **Retrieval** | Parallel dense + sparse search, each returns top-50. |
| **Fusion** | RRF (`k=60`) or weighted fusion with adaptive query weighting. Results filtered by quality gates (both methods must show signal). |
| **Reranking** | Cross-encoder (`mixedbread-ai/mxbai-rerank-large-v1`) re-scores candidates. Results below 0.2 threshold dropped. |
| **Context** | Library Cards expand hits to their parent H2/H3 sections. Deduplicates chunks sharing the same parent. |
| **Intelligent** | If enabled: LLM plans sub-questions, searches each, evaluates results, synthesizes final grounded answer. |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API | FastAPI + Pydantic v2 |
| MCP Server | FastMCP (stdio + HTTP transports) |
| Database | SQLAlchemy 2.0 + SQLite |
| Dense Search | FAISS `IndexFlatIP` + Qwen/Qwen3-Embedding-8B |
| Sparse Search | BM25Plus (`rank-bm25`) |
| Reranking | mixedbread-ai/mxbai-rerank-large-v1 (Cross-Encoder) |
| LLM | DeepSeek-V3.2-Exp (HuggingFace InferenceClient) |
| Chunking | unstructured[md] + tiktoken (cl100k_base) |

---

## Quick Start

```bash
git clone <repo-url>
cd doc-search
pip install -e .

# Copy and configure environment
cp .env.example .env
# Edit .env and add your HF_TOKEN

# REST API (port 8001)
python -m doc_search.presentation.api

# MCP server (stdio)
python -m doc_search.presentation.mcp
```

API docs at `http://localhost:8001/docs`

---

## Documentation

| Document | Covers |
|----------|--------|
| [Architecture](docs/ARCHITECTURE.md) | Clean architecture layers, database schema, entity relationships, project layout |
| [Search Internals](docs/SEARCH.md) | FAISS, BM25, RRF/weighted fusion, quality filters, Library Cards, context expansion, intelligent search |
| [Setup](docs/SETUP.md) | Installation, configuration, Docker, troubleshooting |

---

## Project Structure

```
doc-search/
├── doc_search/
│   ├── presentation/          # API + MCP routes, tools, models
│   │   ├── api/               # FastAPI routes, background tasks, Pydantic models
│   │   └── mcp/               # FastMCP server, tool registration, DB session
│   ├── startup/               # Composition root, DI wiring, app factories
│   ├── core/
│   │   ├── domain/            # Entities, interfaces, fusion algorithms, quality filter
│   │   └── application/       # Use cases: hybrid search, intelligent search, planning, routing, context expansion
│   └── infrastructure/        # Concrete implementations: FAISS, BM25, embeddings, reranking, chunking, SQL data access
└── tests/
```
