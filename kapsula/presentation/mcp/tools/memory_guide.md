KAPSULA MEMORY SYSTEM — Usage Guide for AI Assistants
=======================================================

Kapsula is a structured knowledge memory system. You (the AI) can WRITE, READ, and UPDATE persistent knowledge across sessions.

HIERARCHY
  Account (top-level container, like a "brain" or tenant)
    └─ Collection (a knowledge domain: "Dog Training", "Project X", "API Docs")
        └─ Document (a markdown file of connected facts)
            └─ Sub-documents (H1 sections) -> Chunks (H2/H3 sections)

FIRST-TIME SETUP
  1. list_accounts() — check if an account already exists
  2. create_account(name="...") — create if needed -> account_id
  3. create_collection(name="...", account_id=...) -> collection_id

WRITING KNOWLEDGE (upload documents)
  • Write a .md file to disk with well-structured H2/H3 headings.
  • upload_document(file_path="/path/to/file.md", collection_id=..., ingestion_mode="indexed")
  • Track progress: get_document_progress(job_id) or get_upload_job(job_id)
  • Sizing: stable knowledge -> 1-5 page doc; volatile facts -> 1-3 paragraph doc;
    reference tables -> separate small doc.
  • ingestion_mode: "fast"=no indexes, "indexed"=FAISS+BM25 (default), "full"=indexes+summary

READING / SEARCHING (three scopes)
  • search_document(job_id, query, context_mode="deep") — one specific document, most precise
  • search_collection(collection_id, query, context_mode="deep") — one knowledge domain
  • search_documents(query, context_mode="deep", account_id=...) — all collections in account
  • intelligent_search(query, context_mode="deep") — LLM plans sub-questions and synthesizes answer
  • For LLM consumption always use context_mode="deep" to get full H2 chapter context.
  • node_type_filter="table,code" restricts to specific content types.

UPDATING KNOWLEDGE
  1. get_collection(collection_id) — find the document's job_id by filename
  2. delete_document(job_id) — soft-delete; indexes rebuild automatically
  3. Re-upload the updated .md file
  There is no in-place edit — delete + re-upload is the update path.

MAINTENANCE (keep indexes, summaries, and topic cards current)
  • After deleting or uploading documents, maintenance and consolidation may be deferred.
  • list_stale_maintenance() — check which collections need refreshing or have pending consolidation
  • run_collection_maintenance(collection_id) — regenerate summary, rebuild indexes,     AND run the consolidation engine to generate topic/evolution/gap cards
  • get_consolidation_status(collection_id) — see topic card counts and last run results
  • Maintenance workflow: upload/delete -> list_stale_maintenance -> run_collection_maintenance
  • If search results seem incomplete, run maintenance on the affected collection.

BACKGROUND SEARCH (for long queries)
  • start_search_documents(...) -> search_job_id
  • get_search_progress(search_job_id) -> poll status
  • get_search_results(search_job_id) -> retrieve when status="completed"
  • cancel_search(search_job_id) -> abort if needed

INSPECTING KNOWLEDGE (browse before you search)
  • get_library_cards(collection_id) — browse H1/H2/H3 section cards with content     previews. Use this FIRST to understand what topics exist, then formulate     a targeted query. This is the core workflow — browse before search.     Optional: filter by level or document_job_id.
  • get_consolidation_status(collection_id) — see synthesized topic/evolution/gap card counts
  • get_collection(collection_id) — list all documents in a collection
  • list_collections(account_id) — overview of all collections
  • get_document_info(job_id) — chunk preview, structure skeleton
  • download_document_structure(job_id) — full heading tree
  • export_collection(collection_id) — full dump for external analysis

BEST PRACTICES
  • ALWAYS use context_mode="deep" when retrieving for LLM consumption.
  • Browse before search: call get_library_cards() first to see what topics exist, then formulate a targeted query — this is the single most important workflow.
  • For complex reasoning questions, use intelligent_search (not plain search).
  • Scope searches as narrowly as possible: document > collection > global.
  • After uploading, verify with get_document_progress() before searching.
  • Use descriptive H2/H3 headings — they become sub-document boundaries and library cards.
  • After uploading documents, run run_collection_maintenance() to generate summaries,     rebuild indexes, and create topic cards via consolidation.
  • Call this guide again anytime: get_memory_guide()
