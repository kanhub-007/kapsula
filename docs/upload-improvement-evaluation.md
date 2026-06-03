# Upload Improvement Evaluation

Date: 2026-06-03

## Executive Summary

The current upload pipeline is functionally complete, but the performance and progress behavior are uneven. The strongest improvement path is **not** to immediately parallelize the entire upload pipeline. The safer and higher-value path is:

1. **Fix progress reporting and timeout observability first.** This directly addresses uploads appearing stuck at 80%.
2. **Introduce upload intent / ingestion modes.** Let callers choose between fast upload, fully indexed upload, and full maintenance work.
3. **Batch embeddings across sub-documents.** This reduces Hugging Face round trips without adding database concurrency risk.
4. **Make aggregate indexes incremental or deferred.** The current full aggregate rebuild is the largest avoidable cost.
5. **Move collection summary and account/global index maintenance out of the critical upload path.** These are useful, but they should not block document availability.

The earlier upload improvement plan is directionally correct, especially on the 80% stall and aggregate rebuild cost. This evaluation refines the plan based on the actual code paths and corrects a few details.

---

## Current Upload Flow Verified Against Code

Primary function:

```text
doc_search/presentation/api/tasks.py
process_document_with_subdocuments()
```

Current flow:

```text
1. Set progress 5%: parsing_breadcrumbs
2. Extract sub-documents from H1 breadcrumb structure
3. Set progress 10%: processing_subdocuments
4. For each sub-document:
   - Set progress between 10% and 80%
   - Create SubDocument row
   - Create SubDocumentPage rows
   - Extract parent sections
   - Chunk markdown
   - Add citation metadata
   - Build per-subdocument FAISS and BM25 indexes
   - Save chunks
   - Create subdocument LibraryCard
   - Create parent-section LibraryCards
   - Resolve citation library_card_ids
   - Commit
5. Create main document LibraryCard
6. Set document.status = "completed"
7. Commit
8. Update collection LibraryCard through an LLM call
9. Rebuild collection aggregate index
10. Rebuild account aggregate index if account exists
11. Set progress 100%: completed
```

Indexing helpers:

```text
doc_search/infrastructure/repositories/indexing/document_index_builder.py
doc_search/infrastructure/repositories/indexing/aggregate_index_builder.py
```

Embedding implementation:

```text
doc_search/infrastructure/repositories/embedding/huggingface_embedder.py
```

The startup embedder is wrapped in `CachingEmbedder`, but that cache only applies to single-string query embeddings. Upload batch embeddings are deliberately not cached.

---

## Why Uploads Appear Stuck at 80%

The `process_document_with_subdocuments()` progress calculation is:

```python
progress = 10 + int((subdoc_count / len(subdocs)) * 70)
```

So the last sub-document starts at 80%.

After that 80% update, several potentially slow operations happen with no progress update:

```text
- Finish the last sub-document's embedding, indexing, chunk saving, and citation linking
- Create the main document LibraryCard
- Mark document.status = "completed"
- Generate/update collection LibraryCard through an LLM call
- Rebuild collection aggregate FAISS/BM25 indexes
- Rebuild account aggregate FAISS/BM25 indexes
```

Important nuance: in the current sub-document upload path, the document is marked `completed` **before** collection summary and aggregate index rebuild. The aggregate rebuild helper catches and logs exceptions internally. That means many apparent 80% stalls are not necessarily failed uploads; they may be documents that are already marked completed in the database while the in-memory progress status is still waiting for post-processing to return.

### Most likely causes of the unknown 80% stall

| Rank | Cause | Why likely | Current behavior |
|---:|---|---|---|
| 1 | Aggregate index rebuild embedding call is slow or hanging | It embeds all completed chunks in the collection and then all completed chunks in the account | No progress update until complete |
| 2 | Collection summary LLM call is slow or hanging | `update_collection_library_card()` creates a new HuggingFace chat client and calls the LLM | No timeout wrapper visible in upload task |
| 3 | Last sub-document embedding call is slow | The 80% update happens before last sub-document work finishes | User sees 80% while last subdoc still indexes |
| 4 | In-memory progress and DB status drift | Document can be `completed` in DB while progress remains 80% | Progress endpoint prefers in-memory status if present |
| 5 | Background task/session lifecycle issue | API route passes request DB session into background task | Could behave inconsistently under load |

---

## Corrections to the Earlier Upload Plan

The previous plan is mostly valid, but this evaluation makes the following corrections.

### Correction 1: Aggregate rebuild failures are already non-fatal

The earlier plan states that aggregate index failure can mark the whole upload failed. In the current sub-document path, `_rebuild_collection_aggregate_index()` catches exceptions internally and logs them. It does not mark the document failed.

However, this is still a problem because a hanging aggregate embedding call can keep progress stuck before the final 100% update.

### Correction 2: Collection summary failure is non-fatal, but not timeout-safe

The current upload task catches exceptions from `update_collection_library_card()`. So ordinary exceptions are non-fatal.

The issue is that a long-running or hanging LLM call may not raise quickly. The improvement should focus on timeout control, progress updates, and deferring summary generation.

### Correction 3: Parallel sub-document processing is useful but not the first performance step

Parallelizing sub-documents adds complexity:

```text
- Multiple DB sessions
- SQLite write contention
- HF API rate limits
- Citation/library-card ordering
- Progress aggregation
```

Batching embeddings across sub-documents gives a large performance win with less risk. Parallelism should come after batching and aggregate-index improvements.

### Correction 4: Incremental aggregate indexes are high value but require careful storage changes

Current aggregate indexes store:

```text
- FAISS index
- BM25 pickle
- mapping JSON
```

To make aggregate rebuild incremental safely, the system should also persist aggregate embeddings or enough data to reconstruct without another HF call.

Recommended added artifact:

```text
collection.faiss.index.npy
account.faiss.index.npy
```

This stores normalized or raw embeddings for the aggregate index. New document embeddings can then be appended without re-embedding older chunks.

---

## Recommended Upload Intent Model

Search now has routing modes like `llm`, `fast`, and `auto`. Upload should have a similar concept, but the term should be **ingestion mode** or **upload intent**.

Recommended parameter:

```text
ingestion_mode: "fast" | "indexed" | "full" | "maintenance"
```

### Mode Semantics

| Mode | Behavior | User-facing result | Best for |
|---|---|---|---|
| `fast` | Parse, chunk, save DB records. Defer embeddings, summaries, aggregate indexes. | Document exists quickly but may not be searchable immediately. | Bulk imports, drafts |
| `indexed` | Build per-document/sub-document indexes. Defer collection summary and aggregate/account indexes. | Document is searchable by `search_document`; collection broad search may lag. | Most uploads |
| `full` | Build sub-document indexes, update aggregate indexes, update collection summary. | Everything is immediately current. | Small uploads, demos |
| `maintenance` | No new upload; rebuild stale aggregate indexes and summaries. | Repairs or refreshes collection/account search. | Recovery, scheduled jobs |

Recommended default:

```text
ingestion_mode="indexed"
```

Rationale: document-specific search is available quickly, while expensive collection/account maintenance can run in the background.

---

## Final Recommended Implementation Plan

## Phase 1 — Progress, Status, and Timeout Reliability

### Goal

Make 80% stalls diagnosable and prevent the UI from appearing frozen.

### Changes

1. Add post-subdocument progress stages:

```text
80%  final_subdocument_finishing
83%  document_card
86%  collection_summary
90%  collection_aggregate_index
95%  account_aggregate_index
98%  finalizing
100% completed
```

2. Update progress before and after each expensive operation.

3. Include elapsed time in progress messages:

```text
Rebuilding collection aggregate index: 842 chunks from 7 documents, elapsed 14.2s
```

4. Add timing logs for each stage:

```text
upload.stage job_id=... stage=subdocument_indexing elapsed=...
upload.stage job_id=... stage=collection_summary elapsed=...
upload.stage job_id=... stage=aggregate_collection elapsed=...
upload.stage job_id=... stage=aggregate_account elapsed=...
```

5. Add timeout wrappers or client-level timeout configuration for:

```text
- collection summary LLM call
- aggregate embedding calls
- per-subdocument embedding calls
```

6. Adjust progress fallback logic. If DB says `completed` but in-memory progress is stale, the progress endpoint should not report a stale 80% forever.

Suggested behavior:

```text
if document.status == "completed" and live_status.progress < 100:
    return completed_or_finalizing status with DB completion note
```

### Acceptance Criteria

- No upload remains visibly stuck at 80% without a stage-specific message.
- Progress endpoint reports the expensive post-processing stage.
- Logs show which stage consumed time.
- A document marked completed in DB is not presented as indefinitely stuck at 80%.

### Priority

Highest. This is low-risk and directly addresses the reported symptom.

---

## Phase 2 — Upload Intent / Ingestion Mode

### Goal

Let callers decide whether upload should optimize for speed or full collection maintenance.

### API/MCP Changes

Add optional parameter:

```text
ingestion_mode: str = "indexed"
```

To:

```text
POST /documents/upload
MCP upload_document(file_path, collection_id, max_tokens=512, ingestion_mode="indexed")
```

### Behavior

```text
fast:
  parse + chunk + DB only

indexed:
  parse + chunk + DB + per-subdocument indexes
  defer collection summary and aggregate indexes

full:
  parse + chunk + DB + per-subdocument indexes
  update collection summary
  update collection/account aggregate indexes

maintenance:
  not for upload; separate tool/route to rebuild stale collection/account state
```

### Acceptance Criteria

- Existing behavior can be preserved with `full`.
- Default upload returns faster with `indexed`.
- User can request fully current broad search by selecting `full`.
- Progress messages reflect selected mode.

### Priority

Very high. This is the upload analogue of search routing modes and provides a clean performance/quality tradeoff.

---

## Phase 3 — Batch Embeddings Across Sub-Documents

### Goal

Reduce Hugging Face embedding round trips during upload.

### Current issue

Current upload calls `DocumentIndexBuilder.build()` once per sub-document. Each call embeds that sub-document's chunks separately.

For 15 sub-documents:

```text
15 sub-document embedding calls
+ 1 collection aggregate embedding call
+ 1 account aggregate embedding call
```

### Proposed flow

```text
1. Parse all sub-documents
2. Chunk all sub-documents
3. Collect all valid chunk texts
4. Embed all chunk texts in bounded batches
5. Split returned embeddings by sub-document
6. Build per-subdocument FAISS indexes from precomputed embeddings
7. Build per-subdocument BM25 indexes from texts
```

This requires a builder method like:

```python
DocumentIndexBuilder.build_from_embeddings(
    texts: list[str],
    embeddings: np.ndarray,
    job_id: str,
    account_id: str | None,
    collection_id: str | None,
) -> IndexPaths
```

### Acceptance Criteria

- A many-subdocument upload makes far fewer HF embedding round trips.
- Per-subdocument indexes are identical in content to current behavior.
- Embedding batch size remains bounded, using the existing `batch_size` mechanism.

### Priority

High. This is safer than immediate concurrency and likely gives a meaningful speedup.

---

## Phase 4 — Incremental or Deferred Aggregate Indexes

### Goal

Avoid re-embedding old chunks every time a document is uploaded.

### Current issue

`AggregateIndexBuilder.build()` and `build_account()` collect all completed documents and embed all chunks again.

```text
New document has 200 chunks
Collection already has 2,000 chunks
Current aggregate rebuild embeds 2,200 chunks
Desired behavior embeds only 200 new chunks
```

### Recommended design

Persist aggregate embeddings alongside aggregate indexes:

```text
collection.faiss.index
collection.faiss.index.npy
collection.bm25.pkl
collection.mapping.json

account.faiss.index
account.faiss.index.npy
account.bm25.pkl
account.mapping.json
```

For incremental updates:

```text
1. Load existing mapping and embeddings
2. Collect new document chunks
3. Deduplicate by chunk content hash
4. Embed only new chunks
5. Append new embeddings to existing .npy array
6. Rebuild FAISS locally from the merged embedding array
7. Rebuild BM25 locally from merged texts
8. Save updated mapping
```

This still rebuilds FAISS/BM25 locally, but avoids the expensive HF embedding call for old chunks.

### Alternative short-term option

If incremental index changes are too much for the first implementation, make aggregate rebuild asynchronous/deferred:

```text
- upload completes after per-document/subdocument indexes
- collection/account aggregate indexes are marked stale
- background maintenance job rebuilds them later
```

### Acceptance Criteria

- Adding a document to a large collection no longer embeds old chunks.
- Broad collection search can report whether aggregate indexes are fresh or stale.
- A full rebuild command still exists for repair.

### Priority

High. This is the largest direct performance improvement for repeated uploads.

---

## Phase 5 — Decouple Collection Summary from Upload Critical Path

### Goal

Do not block upload completion on an LLM summary update.

### Current issue

`update_collection_library_card()` runs immediately after document completion. It creates a `HuggingFaceChatClient` and calls the LLM to create or incrementally update the collection summary.

### Recommended change

Move summary work behind an intent gate:

```text
fast/indexed mode:
  mark collection summary stale and return

full mode:
  run summary update with timeout and fallback

maintenance mode:
  rebuild stale summaries
```

Fallback summary should be template-based:

```text
Collection contains N documents and M sub-documents. Recent uploads include: ...
```

### Acceptance Criteria

- Upload completion is not blocked by summary generation in default mode.
- Collection cards remain useful via template fallback.
- Full mode can still generate LLM summaries when desired.

### Priority

Medium-high.

---

## Phase 6 — Upload Job Manager and Persistent Progress

### Goal

Replace ad-hoc in-memory progress tracking with structured upload jobs.

### Current issue

`processing_status` is a plain in-memory dict:

```python
processing_status = {}
```

This means:

```text
- Progress is lost on process restart
- Stale in-memory progress can disagree with DB status
- No recent-job listing
- No retry tracking
```

### Recommended design

Add `UploadJob` and `UploadJobManager`, similar to search jobs, but optionally persisted to the database.

Minimum fields:

```text
job_id
document_id
status
progress
stage
message
error
started_at
updated_at
finished_at
stage_timings_json
```

MCP tools:

```text
list_upload_jobs
get_upload_progress
retry_upload_maintenance
```

### Acceptance Criteria

- Upload progress survives server restarts.
- Stale 80% in-memory progress cannot override completed DB status forever.
- Failed maintenance work can be retried.

### Priority

Medium.

---

## Phase 7 — Bounded Parallelism

### Goal

Further reduce upload wall-clock time after batching and aggregate improvements.

### Recommendation

Only parallelize CPU/local work first:

```text
- markdown chunking
- parent section extraction
- citation metadata matching
- BM25 building
```

Keep HF embedding calls bounded and centralized. If embedding concurrency is added, use a strict env var:

```text
DOCSEARCH_UPLOAD_EMBEDDING_CONCURRENCY=2
```

SQLite writes should remain mostly serialized unless each worker has its own session and writes are short-lived.

### Acceptance Criteria

- Parallelism does not increase HF rate-limit errors.
- SQLite write contention does not increase upload failures.
- Results are deterministic enough for tests.

### Priority

Medium-low. Useful, but not before batching and aggregate changes.

---

## Proposed Status Model

The current single `completed` status hides whether broad-search maintenance is current. A richer status model would help.

Recommended document statuses:

```text
queued
processing
indexed
completed
failed
```

Recommended maintenance flags:

```text
collection_summary_stale: bool
collection_aggregate_stale: bool
account_aggregate_stale: bool
```

Alternative if schema changes should be avoided: store maintenance state in upload job metadata or collection/library-card metadata.

### Semantics

```text
indexed:
  document chunks and per-document/sub-document indexes are available

completed:
  selected ingestion_mode work is complete

maintenance stale flags:
  broad collection/account search may not include the latest upload yet
```

This is especially important if `ingestion_mode="indexed"` becomes the default.

---

## Risk Assessment

| Improvement | Benefit | Risk | Recommendation |
|---|---:|---:|---|
| Progress updates and timings | High | Low | Do immediately |
| Upload ingestion modes | High | Low-medium | Do early |
| Batch embeddings across subdocs | High | Medium | Do before concurrency |
| Incremental aggregate indexes | Very high | Medium-high | Do with tests |
| Defer collection summaries | Medium-high | Low | Do with ingestion modes |
| Upload job manager | Medium | Medium | Do after quick wins |
| Parallel subdoc processing | Medium | High | Defer |
| Persistent upload jobs | Medium | Medium | Useful later |

---

## Recommended First Sprint

Implement these first:

```text
1. Add progress stages after 80%.
2. Add per-stage timing logs.
3. Add stale-progress guard in get_progress / get_document_progress.
4. Add ingestion_mode parameter with default "indexed".
5. In "indexed" mode, skip collection summary and aggregate rebuild.
6. Keep existing full behavior available through ingestion_mode="full".
```

This should quickly solve the apparent 80% stall and make uploads much faster by default without risky internal refactoring.

### Minimal code impact

Files likely touched:

```text
doc_search/presentation/api/models.py
doc_search/presentation/api/routes/documents.py
doc_search/presentation/api/tasks.py
doc_search/presentation/mcp/tools/__init__.py
```

Optional:

```text
docs/SETUP.md
README.md
```

---

## Recommended Second Sprint

Implement embedding and aggregate-index performance work:

```text
1. Add DocumentIndexBuilder.build_from_embeddings().
2. Refactor upload to chunk all sub-documents before embedding.
3. Batch embed all upload chunks once, bounded by batch_size.
4. Save per-subdocument FAISS/BM25 indexes from precomputed embeddings.
5. Add aggregate embedding artifact files (.npy).
6. Implement incremental collection aggregate update.
7. Add maintenance command/tool for full aggregate rebuild.
```

Files likely touched:

```text
doc_search/infrastructure/repositories/indexing/document_index_builder.py
doc_search/infrastructure/repositories/indexing/aggregate_index_builder.py
doc_search/presentation/api/tasks.py
doc_search/presentation/mcp/tools/__init__.py
```

---

## Suggested Tests

Add tests around the highest-risk behavior.

### Progress tests

```text
- upload progress emits stages beyond 80%
- completed DB status cannot be masked by stale in-memory 80% progress
- ingestion_mode="indexed" reaches 100% without collection summary/aggregate rebuild
```

### Embedding tests

```text
- many sub-documents use one logical embedding pass
- build_from_embeddings creates searchable FAISS index
- chunk-to-subdocument mapping remains correct after batch split
```

### Aggregate tests

```text
- incremental aggregate update embeds only new chunks
- full rebuild and incremental update produce equivalent mappings
- duplicate chunks are not added twice
- stale aggregate flag is set and cleared correctly
```

### Failure tests

```text
- collection summary timeout does not fail upload
- aggregate rebuild failure leaves document searchable by document-level search
- missing HF token fails clearly at embedding stage
```

---

## Final Recommendation

The best upload improvement strategy is to make upload **intent-aware** and separate document availability from collection maintenance.

Recommended default behavior:

```text
ingestion_mode="indexed"
```

This means:

```text
- Upload parses, chunks, saves, and builds per-subdocument indexes.
- Document-specific search works quickly.
- Collection summary and broad aggregate indexes are deferred or run in maintenance.
- Users can still request ingestion_mode="full" when immediate broad-search freshness matters.
```

This mirrors the search-side improvement philosophy: expose speed/quality tradeoffs explicitly, avoid expensive work unless needed, and make long operations observable.

Most likely fix for current 80% issue:

```text
Add explicit progress stages and avoid running summary + aggregate maintenance synchronously in default uploads.
```

Most important performance fix:

```text
Stop re-embedding all old collection/account chunks on every upload.
```
