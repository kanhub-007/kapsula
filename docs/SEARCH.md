# Search Internals

This document covers the retrieval, fusion, quality filtering, reranking, context expansion, and intelligent search pipelines in detail.

---

## Dense Retrieval — FAISS

### Index Type
`faiss.IndexFlatIP` — exact inner product search. With L2-normalized vectors, inner product equals cosine similarity.

### Embedding Model
`Qwen/Qwen3-Embedding-8B` via HuggingFace InferenceClient. All embeddings are L2-normalized before insertion.

### Search Process
```python
q_emb = embedder.embed(query).astype("float32")
faiss.normalize_L2(q_emb)
distances, indices = index.search(q_emb, k=50)
```

Each result gets: `index`, `content`, `original_rank` (0-indexed), `dense_score` (inner product, range 0–1).

### Strengths
- Semantic/conceptual matching
- Definitional and broad queries
- Finds related concepts even with different vocabulary

---

## Sparse Retrieval — BM25

### Algorithm
BM25Plus — adds a δ constant to the standard BM25 formula to avoid negative IDF-adjusted scores on short documents.

### Implementation
Uses `rank-bm25` library. `BM25Plus(corpus)` where `corpus` is a list of tokenized chunk texts.

### Tokenization
Custom tokenizer in `text_processing.py`:
```python
words = re.findall(r"\b\w+\b", text.lower())
tokens = [simple_stem(w) for w in words]
```

**Stemming rules** (simple, rule-based):
| Suffix | Action | Example |
|--------|--------|---------|
| `ies` | → `y` | queries → query |
| `es` | remove | classes → class |
| `s` | remove | documents → document |
| `ed` | remove | processed → process |
| `ing` | remove | processing → process |

Stem cache (`_STEM_CACHE` dict) avoids recomputation.

### Search Process
```python
tokens = tokenize(query)
scores = bm25.get_scores(tokens)
top_indices = np.argsort(scores)[::-1][:k]
```

Each result gets: `index`, `content`, `original_rank`, `sparse_score` (raw BM25 score, can be >1).

### Strengths
- Exact keyword matching
- Technical terms, codes, specific names
- Short, precise queries

---

## Fusion Strategies

Both fusion methods receive dense results (dense_score per item) and sparse results (sparse_score per item). Sparse scores are normalized by `max_sparse` for combination.

### Weighted Fusion

```
score = dense_weight × dense_score + sparse_weight × (sparse_score / max_sparse)
```

**Default weights**: 0.7 dense, 0.3 sparse.

**Adaptive query weighting** (`get_adaptive_weights()`):
| Query Type | Detection | Dense | Sparse |
|-----------|-----------|-------|--------|
| Definitional | "what is", "define", "explain" | 0.75 | 0.25 |
| Procedural | "how to", "steps", "guide" | 0.65 | 0.35 |
| Specific | ≤3 tokens, uppercase/digits, not concept words | 0.40 | 0.60 |
| General | Everything else | 0.70 | 0.30 |

Concept words excluded from "specific" detection: `audit`, `security`, `fee`, `support`, `architecture`, etc.

**Dynamic adjustment**: If top-5 dense scores average <0.5, weights shift to 0.3/0.7 (lean on sparse). If 0.5–0.65, use balanced 0.5/0.5.

### RRF — Reciprocal Rank Fusion

```
RRF_score = Σ 1 / (k + rank + 1)
```

Where `k=60` and `rank` is the 0-indexed position from each retrieval method. Results appearing in both methods get contributions from both lists.

**Advantages over weighted**: No score calibration needed. Handles situations where one method vastly outperforms the other — rank position is more meaningful than raw scores.

### Implementation Detail

Both `WeightedFusion` and `RRFFusion` produce a merged `result_map` keyed by chunk index, then sort by `score`, then apply quality filtering.

---

## Quality Filtering

After fusion, each result must pass one of four quality gates (`passes_quality_filter()` in `quality_filter.py`):

| Gate | Condition | Rationale |
|------|-----------|-----------|
| Both signals | dense > 0.15 **AND** sparse_norm > 0.1 | Both methods found this result |
| Strong dense | dense ≥ 0.55 **AND** sparse_norm > 0.02 | Very strong semantic match with some keyword signal |
| Balanced | dense ≥ 0.4 **AND** sparse_norm > 0.05 | Good signal from both |
| Strong sparse | sparse_norm ≥ 0.3 **AND** dense ≥ 0.25 | Strong keyword match with some semantic signal |

If no gate passes, the result is discarded. This ensures hybrid search requires hybrid agreement — no single-method-only results.

The intuition: a search that's "hybrid" at retrieval but then lets pure-dense or pure-sparse results through at ranking time isn't truly hybrid. These gates enforce that both methods contribute meaningful signal.

---

## Reranking

### Model
`mixedbread-ai/mxbai-rerank-large-v1` via `sentence-transformers` CrossEncoder.

### Lazy Loading
The model is loaded on first `rerank=True` call, not at searcher construction. This avoids paying the load cost when reranking is disabled.

### Process
```python
pairs = [(query, candidate_content) for candidate in candidates]
scores = model.predict(pairs, batch_size=16)

# Threshold: filter out scores < 0.2
kept = [c for c in candidates if c["rerank_score"] >= 0.2]
```

### Pipeline Position
Reranking runs after fusion and quality filtering, **before** context expansion. This ensures the cross-encoder sees chunk-level content, not expanded parent sections which would be noisy.

---

## Context Expansion — Russian Doll via Library Cards

### How Library Cards Are Created

During document processing, the `parent_section_extractor` scans the markdown for H1, H2, and H3 headings. For each heading, it captures:
- The heading level and text
- The full text content from that heading to the next heading of equal or higher level
- A SHA256 hash of that content (`doc_id`)

These are stored as `LibraryCard` rows. Each card's content is the **entire** section — it already includes all nested sub-sections and chunks.

### How Chunks Link to Cards

During ingestion, each chunk records in its `chunk_metadata` a `parents` JSON object:
```json
{
  "parents": {
    "immediate": "sha256_of_parent_H3",
    "chapter": "sha256_of_parent_H2",
    "page": "sha256_of_parent_H1"
  }
}
```

These hashes are resolved to `library_card.id` values after all cards are saved.

### Search-Time Expansion

When `context_mode` is enabled:

1. For each search result, look up the chunk by `(document_id, chunk_index, sub_document_id)`
2. Parse `chunk_metadata.parents` to get the parent hash
3. Query `LibraryCard` by `doc_id` (the hash) and `sub_document_id`
4. Replace `expanded_content` with the full parent section text
5. Store `chunk_content` (original) and `parent_hash` for dedup

### Context Modes

| Mode | Parent Level | Use Case |
|------|-------------|----------|
| `none` | — | Fast retrieval, specific facts |
| `narrow` | H3 (`immediate`) | Context for specific details |
| `deep` | H2 (`chapter`) | Broader topic understanding |

### Fallback

If the requested parent is not found:
- `narrow` (H3 missing) → falls back to H2 `chapter`
- `chapter` (H2 missing) → falls back to H1 `page`

### Deduplication

Multiple chunks often belong to the same parent section. After expansion:
- Results are deduplicated by `parent_hash`
- First occurrence kept; subsequent ones merge their scores into `contributing_scores`
- Final score is `max(contributing_scores)`

This avoids returning the same expanded section multiple times from different chunks.

---

## Intelligent Search Pipeline

### Query Planning

`QueryPlanner` uses DeepSeek-V3.2-Exp to decompose complex queries into sub-questions targeting specific document sections.

**Input**: Original query + document structure (H1/H2/H3 headings from Library Cards).

**Output**: Either a single refined query or 2–5 sub-questions, each aimed at specific sections.

### Parallel Execution

Sub-questions execute in parallel via `asyncio.gather`. Each:
1. Runs hybrid search with the sub-question
2. Gets top-k results
3. Feeds results to `evaluate_and_answer()` — LLM generates intermediate answer

### Synthesis

`_combine_sub_answers()` merges all intermediate answers into one coherent response:
- System prompt enforces natural, conversational tone
- Explicit rule: "Do NOT mention sub-question numbers"
- `temperature=0.3` for consistent, factual output

### Topic Card Overview (Knowledge Overview)

Before generating the final answer, intelligent search queries the collection's topic cards
(from the consolidation engine) and includes them as a **Knowledge Overview** section:

```
--- Knowledge Overview (synthesized) ---
[Topic Name] (importance: 0.9): Synthesized topic summary...
```

This gives the LLM a high-level understanding of the knowledge domain before it
synthesizes from raw chunks, resulting in more coherent cross-document answers.

### Search Miss Logging

Low-result searches (<3 results at collection scope) are logged to `search_miss_log`
for later gap detection by the consolidation engine.

### Grounding

Strict prompt rules prevent hallucination:
- Answer **only** from provided context
- Never use pre-trained knowledge
- If context insufficient: "I don't have enough information to answer that question."

### Streaming (SSE)

Collection-level intelligent search supports SSE streaming with events:
`planning` → `subquestion_start` × N → `subquestion_complete` × N → `final_answer`

---

## Node-Type Filtering

Pre/post-fusion filtering by content type. Each chunk's `chunk_metadata` stores `node_type`:

| Type | Detected By |
|------|------------|
| `text` | Default for paragraphs and headings |
| `table` | `unstructured` Table elements |
| `code` | Backtick fences, function patterns, indentation density, symbol density |

Filter is applied post-fusion, pre-reranking. Multiple types can be specified: `node_type_filter=["table", "code"]`.

---

## Result Filtering During Indexing

Before indexes are built, chunks are filtered:
- Minimum 50 characters
- Must pass `is_meaningful_chunk()` — at least 5 words of 2+ characters

Chunks failing these are excluded from both FAISS and BM25 indexes.
