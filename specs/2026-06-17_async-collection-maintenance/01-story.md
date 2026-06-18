# Async Collection Maintenance

## User Story
As a user of kapsula's MCP interface, I want to trigger collection maintenance (summary refresh, index rebuild, consolidation) without the tool call blocking for 5+ minutes and timing out, so that I can reliably maintain collections of any size.

## Context

`run_collection_maintenance` currently runs all work synchronously inside the MCP tool handler. For a collection with 60+ documents, this includes:

1. **Summary refresh** — one LLM call per unsummarized document
2. **Aggregate index rebuild** — FAISS + BM25 index construction across all chunks
3. **Consolidation** — topic clustering (1 LLM call), topic card generation (1 LLM call per cluster), evolution card (1 LLM call), gap card analysis (1 LLM call)

This routinely exceeds the MCP protocol's 300-second tool-call timeout. Only the smallest collections (under ~25 documents) complete within the window. Larger collections cause the error:

```
kapsula error: MCP request timeout after 300002ms (configured 300000ms): tools/call
```

The codebase already has an established async pattern: `upload_document` creates a job record in the `upload_jobs` table, starts processing in a daemon thread via `ThreadPoolBackgroundProcessor`, and returns a `job_id` immediately. The client polls progress via `get_upload_job(job_id)`.

This feature applies the same async job pattern to collection maintenance.

## Non-Goals
Things explicitly NOT being built in this iteration:
- Changing the 300-second MCP timeout (it's a protocol-level setting in fastmcp/pi)
- Queueing or rate-limiting multiple concurrent maintenance jobs
- Adding progress percentage estimates (stage-based status only)
- Changing the consolidation LLM prompts or logic
- Persisting maintenance results beyond the job lifecycle
