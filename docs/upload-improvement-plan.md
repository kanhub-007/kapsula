# Doc-Search Upload Improvement Plan

Date: 2026-06-03

## Current Diagnosis

Upload is functional but has two problems:

1. **Uploads stall at 80%** — the progress bar jumps from 80% to 100% with no intermediate updates while expensive operations run (collection LLM summary, aggregate index rebuild).
2. **Upload is slower than necessary** — each sub-document calls the HF embedder independently, and the aggregate index rebuild re-embeds ALL chunks across ALL documents from scratch.

Measured behavior for a medium document (~200KB, ~15 sub-documents):

```text
upload_document("hyperliquid-docs.md")
→ sub-document processing: ~15 embedding calls
→ aggregate index rebuild: 1 more embedding call (re-embeds everything)
→ total: ~16 HF embedding calls + 1 LLM call for collection summary
```

The aggregate index rebuild is the biggest single cost and is done synchronously after the sub-document loop, with no progress reporting.

## Where 80% Stall Happens

The progress in `process_document_with_subdocuments` is:

```text
5%   — parsing breadcrumbs
10%  — first sub-document starts
...  — sub-document loop (10-80%)
80%  — last sub-document (progress = 10 + (N/N)*70 = 80)
      ← NO MORE PROGRESS UPDATES ↓
      — finish last sub-document (chunk, embed, save, link)
      — create main document LibraryCard
      — update_collection_library_card()  ← LLM call, can hang
      — _rebuild_collection_aggregate_index()  ← re-embeds everything, can be slow
100% — finally marked complete
```

The gap between 80% and 100% contains:

| Operation | Cost | Can fail silently? |
|---|---|---|
| Last sub-document completion | 1 embedding call + DB writes | Rarely |
| Main document LibraryCard | Quick DB insert | No |
| Collection summary (LLM) | 1 LLM chat call | **Yes — timeout, rate limit** |
| Aggregate FAISS index | 1 embedding call for ALL chunks in collection | **Yes — HF timeout** |
| Aggregate BM25 index | Local CPU (fast) | No |
| Account aggregate index | 1 embedding call (if account exists) | **Yes — HF timeout** |

The most frequent stall culprits are the **LLM call** for collection summary and the **aggregate embedding call**.

## Main Problems to Solve

### 1. 80% Progress Stall (UX)

No progress is reported during the most expensive operations. Users see "80%" indefinitely and assume the upload is broken.

### 2. Redundant Aggregate Rebuild (Performance)

Every upload triggers a full aggregate index rebuild that re-embeds every chunk in the collection. For a collection with 10 documents of 200 chunks each, that's 2000 re-embeddings when only 200 new chunks were added.

### 3. Sequential Sub-Document Processing (Performance)

Sub-documents are processed one at a time. Each one calls the HF embedder. These are independent and could run concurrently.

### 4. No Retry / Timeout Handling (Reliability)

If the LLM call or HF embedding call fails mid-upload, the document is marked "failed" even though chunking and sub-document indexing completed successfully. The aggregate index is left stale.

### 5. No Upload Job Management (Observability)

Upload jobs use a plain `processing_status` dict. No structured job tracking, no persistence across restarts, no timeout detection.

---

# Phase 1 — Fix the 80% Stall (Quick Win)

## Goal

Add progress updates for the post-loop operations so users never see a stuck progress bar.

## Changes

### 1.1 Add Progress Updates in `process_document_with_subdocuments`

File:

```text
doc_search/presentation/api/tasks.py
```

After the sub-document loop, add explicit progress updates:

```python
# After sub-document loop — before LLM call
processing_status[job_id] = {
    "status": "processing",
    "progress": 82,
    "stage": "collection_summary",
    "message": "Generating collection summary...",
}

# After collection summary — before aggregate index
processing_status[job_id] = {
    "status": "processing",
    "progress": 88,
    "stage": "aggregate_index",
    "message": "Rebuilding collection search index...",
}

# After aggregate index
processing_status[job_id] = {
    "status": "processing",
    "progress": 95,
    "stage": "finalizing",
    "message": "Finalizing document...",
}
```

### 1.2 Add Granular Progress to Aggregate Index Rebuild

File:

```text
doc_search/infrastructure/repositories/indexing/aggregate_index_builder.py
```

Accept an optional `progress_callback` that reports progress during embedding:

```python
def build(
    self, db, collection_id, ..., progress_callback=None
):
    texts, mapping = self._collect_texts_and_mapping(docs)
    if progress_callback:
        progress_callback(50, f"Embedding {len(texts)} chunks...")
    embeddings = self._embedder.embed(texts)
    if progress_callback:
        progress_callback(80, "Building FAISS index...")
    # ... build indexes ...
    if progress_callback:
        progress_callback(100, "Aggregate index complete")
```

### 1.3 Add Timeout + Graceful Degradation for LLM Summary

The `update_collection_library_card` LLM call should have a timeout. If it fails, the document should still complete — just without an updated collection summary.

```python
try:
    update_collection_library_card(document.id, db)
except Exception as e:
    logger.error("Collection summary update failed (non-fatal): %s", e)
    # Continue — aggregate index and chunk data are still valid
```

## Acceptance Criteria

- Progress moves smoothly from 5% → 10% → ... → 80% → 82% → 88% → 95% → 100%
- Users never see a stuck 80% bar for more than a few seconds
- If the LLM summary call fails, the document still completes successfully
- Aggregate index rebuild reports its own sub-progress

---

# Phase 2 — Incremental Aggregate Indexes

## Goal

Stop re-embedding every chunk in the collection every time a document is uploaded.

## Current Problem

```text
_rebuild_collection_aggregate_index()
  → AggregateIndexBuilder.build()
    → queries ALL completed documents in collection
    → collects ALL chunks from ALL documents
    → embedder.embed(ALL chunks)  ← re-embeds old chunks
    → builds fresh FAISS + BM25
```

For collection with 10 docs × 200 chunks = 2000 total chunks, adding 1 doc with 200 chunks means re-embedding 2000 chunks when only 200 are new.

## Approach: Append-Only Incremental Build

### 2.1 Track Index State

New file or section in aggregate index builder:

```python
class IncrementalAggregateIndexBuilder:
    """Builds aggregate indexes incrementally — only embeds new chunks."""

    def add_document(self, db, document, ...):
        # 1. Load existing aggregate index
        existing_faiss, existing_bm25, existing_mapping = self._load_existing(...)

        # 2. Collect only NEW chunks from this document
        new_texts, new_mapping = self._collect_texts_for_document(document)
        # Deduplicate against existing chunks
        new_texts, new_mapping = self._deduplicate(new_texts, new_mapping, existing_mapping)

        if not new_texts:
            logger.info("No new chunks to add to aggregate index")
            return

        # 3. Embed only new chunks
        new_embeddings = self._embedder.embed(new_texts)

        # 4. Merge into existing indexes
        if existing_faiss:
            merged_faiss = self._merge_faiss(existing_faiss, new_embeddings)
        else:
            merged_faiss = self._build_faiss(new_embeddings)

        if existing_bm25:
            merged_bm25 = self._merge_bm25(existing_bm25, new_texts)
        else:
            merged_bm25 = self._build_bm25(new_texts)

        merged_mapping = (existing_mapping or []) + new_mapping

        # 5. Save merged indexes
        self._save(merged_faiss, merged_bm25, merged_mapping, ...)
    ```

### 2.2 FAISS Merge Strategy

FAISS `IndexFlatIP` does not support native incremental insert. Options:

**Option A: Rebuild from stored vectors (recommended)**
```python
# Store embeddings alongside index
embeddings_path = faiss_path + ".npy"  # numpy array of all embeddings

def _merge_faiss(self, existing_faiss_path, new_embeddings):
    # Load existing embeddings
    existing = np.load(existing_faiss_path + ".npy")
    # Concatenate
    merged = np.vstack([existing, new_embeddings.astype("float32")])
    # Normalize
    faiss.normalize_L2(merged)
    # Build fresh index (fast — no HF call needed)
    index = faiss.IndexFlatIP(merged.shape[1])
    index.add(merged)
    # Save both index and embeddings
    faiss.write_index(index, faiss_path)
    np.save(faiss_path + ".npy", merged)
```

This is fast because we're only doing NumPy concatenation + FAISS rebuild (no embedding calls).

**Option B: IVF index with `add()` support**
More complex, not needed for current scale.

### 2.3 BM25 Merge Strategy

BM25Plus doesn't support incremental add natively, but we can rebuild from stored tokenized corpus:

```python
def _merge_bm25(self, existing_bm25_path, new_texts):
    # Load existing corpus texts
    with open(existing_bm25_path + ".texts.json") as f:
        existing_texts = json.load(f)

    # Merge
    all_texts = existing_texts + new_texts
    corpus = [tokenize(t) for t in all_texts]
    bm25 = BM25Plus(corpus)  # Rebuild is fast — no HF call

    # Save
    with open(bm25_path, "wb") as f:
        pickle.dump({"bm25": bm25, "texts": texts}, f)
    with open(bm25_path + ".texts.json", "w") as f:
        json.dump(all_texts, f)
```

### 2.4 Deduplication

Use content hash to avoid re-adding chunks that already exist:

```python
def _deduplicate(new_texts, new_mapping, existing_mapping):
    existing_hashes = {
        hashlib.sha256(m["content"].encode()).hexdigest()
        for m in existing_mapping
        if m.get("content")
    }

    kept_texts = []
    kept_mapping = []
    for text, map_entry in zip(new_texts, new_mapping):
        chunk_hash = hashlib.sha256(text.encode()).hexdigest()
        if chunk_hash not in existing_hashes:
            kept_texts.append(text)
            kept_mapping.append(map_entry)

    return kept_texts, kept_mapping
```

## Acceptance Criteria

- Second document upload to a collection only embeds the new document's chunks
- Aggregate index rebuild time drops from O(collection_size) to O(new_document_size)
- First document upload still works (creates fresh indexes)
- Search results from aggregate indexes are identical to full rebuild

---

# Phase 3 — Parallel Sub-Document Processing

## Goal

Process sub-documents concurrently since they are independent.

## Current Flow

```python
for breadcrumb_key, pages in subdocs.items():
    # Sequential:
    #   chunk → embed → index → save chunks → save cards → resolve citations
    #   (each sub-doc makes 1 HF embedding call)
```

## Proposed Flow

```python
import concurrent.futures

def _process_one_subdoc(breadcrumb_key, pages, document_id, max_tokens, ...):
    """Process a single sub-document. Returns (chunks, subdoc_id, index_paths)."""
    # All the current per-subdocument logic, extracted into a function
    ...

with concurrent.futures.ThreadPoolExecutor(max_workers=DOCSEARCH_UPLOAD_CONCURRENCY) as pool:
    futures = {
        pool.submit(_process_one_subdoc, key, pages, ...): key
        for key, pages in subdocs.items()
    }
    for future in concurrent.futures.as_completed(futures):
        result = future.result()
        # Accumulate results
        ...

# After all sub-docs complete: sequential finalization
# (LibraryCard creation, collection summary, aggregate index)
```

### 3.1 Concurrency Limit

Env var:

```text
DOCSEARCH_UPLOAD_CONCURRENCY=3
```

Keep low (2-4) to avoid hammering Hugging Face with simultaneous embedding calls. The HF Inference API has rate limits.

### 3.2 Thread Safety Considerations

Each sub-document needs its own DB session:

```python
def _process_one_subdoc(breadcrumb_key, pages, document_id, max_tokens):
    db = SessionLocal()  # Fresh session per thread
    try:
        # ... process sub-document ...
        db.commit()
        return result
    finally:
        db.close()
```

Or use a connection pool with thread-local sessions.

## Acceptance Criteria

- Multiple sub-documents process in parallel
- Upload wall-clock time drops for multi-subdocument files
- No database session conflicts
- No HF rate-limit errors
- Failed sub-documents don't crash the whole upload

---

# Phase 4 — Embedding Batching for Upload

## Goal

Batch embedding calls across sub-documents to reduce HF round-trips.

## Current Flow

Each sub-document makes its own `embedder.embed(texts)` call:

```text
Sub-doc 1: embed([chunk1, chunk2, ..., chunk20])  → 1 HF call
Sub-doc 2: embed([chunk1, chunk2, ..., chunk15])  → 1 HF call
Sub-doc 3: embed([chunk1, chunk2, ..., chunk25])  → 1 HF call
...
Total: N HF calls for N sub-documents
```

## Proposed: Collect-Then-Batch

```python
# Phase 1: Collect all chunks from all sub-documents (no embedding)
all_chunks_by_subdoc = {}
for breadcrumb_key, pages in subdocs.items():
    subdoc_content = "\n\n".join(page["content"] for page in pages)
    chunks = MarkdownChunker(max_tokens=max_tokens).chunk(subdoc_content)
    all_chunks_by_subdoc[breadcrumb_key] = chunks

# Phase 2: Batch embed ALL chunks from ALL sub-documents in ONE call
all_texts = []
for chunks in all_chunks_by_subdoc.values():
    all_texts.extend(c["content"] for c in chunks)

all_embeddings = embedder.embed(all_texts)  # Single HF call

# Phase 3: Distribute embeddings back to sub-documents and build indexes
offset = 0
for breadcrumb_key, chunks in all_chunks_by_subdoc.items():
    n = len(chunks)
    subdoc_embeddings = all_embeddings[offset:offset + n]
    # Build FAISS from pre-computed embeddings
    _build_faiss_from_embeddings(subdoc_embeddings, ...)
    # Build BM25 from texts
    _build_bm25_from_texts([c["content"] for c in chunks], ...)
    offset += n
```

This reduces N HF calls to 1 HF call.

### 4.1 Tradeoff

- Pro: Fewer HF API calls (faster, less rate-limit risk)
- Con: Larger single batch (memory, HF API limits)
- Mitigation: Chunk the batch if it exceeds HF API max batch size

## Acceptance Criteria

- Documents with 10+ sub-documents make 1 embedding call instead of 10+
- Embedding results are correctly distributed to sub-document indexes
- Search quality is unchanged
- Memory usage stays bounded (batch if >1000 chunks)

---

# Phase 5 — Upload Job Manager

## Goal

Replace the ad-hoc `processing_status` dict with a proper job manager, mirroring `SearchJobManager`.

## New File

```text
doc_search/presentation/mcp/upload_jobs.py
```

or extend the existing search job system to support upload jobs.

### 5.1 UploadJob Model

```python
@dataclass
class UploadJob:
    job_id: str              # UUID
    status: str              # queued | processing | completed | failed
    progress: int            # 0-100
    stage: str               # parsing | chunking | embedding | indexing | summary
    message: str
    document_filename: str
    collection_name: str
    chunk_count: int = 0
    subdocument_count: int = 0
    duration: float = 0.0
    error: str | None = None
    created_at: datetime
    updated_at: datetime
```

### 5.2 UploadJobManager

```python
class UploadJobManager:
    def start(self, params: dict) -> UploadJob: ...
    def update(self, job_id: str, **kwargs) -> None: ...
    def get(self, job_id: str) -> UploadJob | None: ...
    def list_recent(self, limit: int = 50) -> list[UploadJob]: ...
    def clear_completed(self, older_than: timedelta) -> int: ...
```

### 5.3 Persistence

Optionally persist jobs to a SQLite table for survival across restarts:

```sql
CREATE TABLE upload_jobs (
    job_id TEXT PRIMARY KEY,
    document_id INTEGER,
    status TEXT,
    progress INTEGER,
    stage TEXT,
    message TEXT,
    error TEXT,
    created_at TEXT,
    updated_at TEXT
);
```

## Acceptance Criteria

- Upload progress survives server restart
- Can list recent uploads with `list_upload_jobs` MCP tool
- Old completed jobs are cleaned up automatically
- Failed jobs include error details

---

# Phase 6 — Resume / Retry for Partial Failures

## Goal

If an upload fails during the aggregate index rebuild, don't lose the chunk and sub-document data.

## Current Behavior

```python
except Exception as e:
    document.status = "failed"
    db.commit()
```

The entire document is marked failed even if all chunking and sub-document indexing succeeded.

## Proposed: Multi-Stage Completion

```python
# Stage 1: Chunking + Sub-document indexes (persist early)
document.status = "indexed"  # New status: chunks exist, indexes built
db.commit()

# Stage 2: Collection summary (best-effort)
try:
    update_collection_library_card(document.id, db)
except Exception:
    logger.warning("Collection summary failed — document is still searchable")

# Stage 3: Aggregate index (retry-able)
try:
    _rebuild_collection_aggregate_index(db, document, job_id)
except Exception:
    logger.warning("Aggregate index rebuild failed — retry later")

# Stage 4: Mark complete
document.status = "completed"
db.commit()
```

A new status `"indexed"` means the document is searchable via sub-document indexes but its chunks aren't in the aggregate index yet.

A background task or next upload can rebuild the aggregate index to include `"indexed"` documents.

## Acceptance Criteria

- Chunk data is never lost due to post-processing failures
- Documents with status "indexed" can be searched via `search_document`
- Aggregate index can be rebuilt on demand
- Failed aggregate rebuilds are retried automatically

---

# Phase 7 — LLM Call Optimization for Collection Summary

## Goal

Reduce or eliminate the LLM call during upload while keeping collection cards useful.

## Current Cost

Every upload triggers `update_collection_library_card()` which makes 1 LLM chat call to Hugging Face. This:

- Takes 2-10 seconds
- Can timeout
- Costs tokens

## Options

### 7.1 Batch Collection Summaries (Recommended)

Don't call the LLM during upload. Instead, run collection summary generation asynchronously on a schedule or after multiple uploads:

```python
# In process_document_with_subdocuments:
# DON'T call update_collection_library_card here

# Instead, add a count
collection.summary_stale = True
collection.pending_summary_count += 1
db.commit()

# Background worker:
if collection.pending_summary_count >= 3:  # Batch every 3 uploads
    update_collection_library_card(document.id, db)
    collection.pending_summary_count = 0
```

### 7.2 Use Embedding Cache for Collection Card

If the collection card is a simple aggregation, skip the LLM entirely and use a template:

```python
def generate_collection_summary_template(collection, documents):
    topics = set()
    for doc in documents:
        for subdoc in doc.sub_documents:
            topics.add(subdoc.breadcrumb_key)
    return (
        f"This collection contains {len(documents)} documents "
        f"covering {len(topics)} topics: {', '.join(sorted(topics)[:10])}."
    )
```

### 7.3 Add Timeout + Fallback

```python
try:
    summary = asyncio.wait_for(
        generate_summary_async(...),
        timeout=15.0  # seconds
    )
except asyncio.TimeoutError:
    logger.warning("Collection summary LLM call timed out — using template fallback")
    summary = generate_collection_summary_template(...)
```

## Acceptance Criteria

- Upload time is not gated on LLM response time
- Collection cards are still generated (eventually)
- Failed LLM calls don't block document completion

---

# Phase 8 — Upload Progress MCP Tools

## Goal

Expose upload progress through MCP tools, not just the HTTP API.

## New MCP Tools

```text
get_upload_progress(job_id: str) -> str
list_upload_jobs(limit: int = 20) -> str
retry_upload(job_id: str) -> str
```

These mirror the existing `get_document_progress` tool but are backed by the `UploadJobManager` instead of the in-memory dict.

## Acceptance Criteria

- MCP clients can track upload progress without hitting the HTTP API
- `list_upload_jobs` shows recent uploads with status
- `retry_upload` re-queues a failed upload

---

# Phase 9 — Document Re-Processing

## Goal

Allow re-processing a document when the chunking strategy or embedding model changes.

## New MCP Tools

```text
reprocess_document(job_id: str, max_tokens: int = 512) -> str
```

This:
1. Deletes existing chunks, sub-documents, library cards for the document
2. Deletes existing FAISS/BM25 indexes for the document
3. Re-runs `process_document_with_subdocuments`
4. Rebuilds aggregate indexes

## Acceptance Criteria

- Document can be re-processed with different parameters
- Old data is fully cleaned up before re-processing
- New job_id is assigned
- Aggregate indexes are updated correctly

---

# Phase 10 — Observability: Upload Metrics

## Goal

Track upload performance and failure rates.

## Metrics to Track

```python
# Per-upload metrics
upload_total_time: float
chunking_time: float
embedding_time: float
indexing_time: float
summary_time: float
aggregate_time: float
subdocument_count: int
chunk_count: int
hf_embedding_calls: int
hf_llm_calls: int

# Aggregated metrics
uploads_total: int
uploads_failed: int
avg_upload_time: float
p95_upload_time: float
```

## Approach

Add structured logging with timing context managers:

```python
with timing("embedding", metrics):
    embeddings = embedder.embed(texts)

# Logs:
# upload.metrics job_id=abc123 stage=embedding elapsed=2.34s chunks=200
```

## Acceptance Criteria

- Every upload logs per-stage timing
- Failed uploads log which stage failed
- Metrics are queryable for debugging

---

# Recommended Implementation Order

## Sprint 1 — Fix the 80% Stall (Quick Win)

```text
Phase 1: Better progress reporting + LLM timeout/fallback
```

This is the highest-impact, lowest-risk change. Users immediately stop seeing stuck uploads.

## Sprint 2 — Performance

```text
Phase 2: Incremental aggregate indexes
Phase 4: Embedding batching for upload
```

These dramatically reduce the number of HF embedding calls per upload.

## Sprint 3 — Parallelism + Reliability

```text
Phase 3: Parallel sub-document processing
Phase 6: Multi-stage completion (resilience)
```

These make uploads faster and more resilient to partial failures.

## Sprint 4 — Operations

```text
Phase 5: Upload job manager
Phase 7: LLM call optimization
Phase 8: Upload progress MCP tools
Phase 10: Observability metrics
```

These improve the developer experience and debugging.

## Sprint 5 — Polish

```text
Phase 9: Document re-processing
```

Nice-to-have for model/chunking strategy changes.

---

# Minimal First Implementation

For the fastest meaningful improvement, start with:

```text
1. Phase 1: Add progress updates between 80% and 100%
2. Phase 1: Make collection summary failure non-fatal
3. Phase 2: Incremental aggregate indexes
4. Phase 4: Batch embeddings across sub-documents
```

Expected benefits:

```text
No more 80% stall
Collection summary failures don't break uploads
2nd+ upload to a collection is 5-10x faster
Documents with many sub-documents upload faster
```
