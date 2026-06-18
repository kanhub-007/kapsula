# Split tasks.py into Modular Background Processing Pipeline

## User Story
As a developer maintaining the document upload pipeline, I want `kapsula/presentation/api/tasks.py` split into focused, testable modules so that I can understand, test, and modify individual processing stages without touching a 1400+ line God File.

## Context

`tasks.py` (currently ~1417 lines after partial refactoring) orchestrates the entire document upload lifecycle: structure extraction → parent section extraction → chunking → citation metadata → chunk persistence → parent section persistence → chunk linking → index building → aggregate index rebuild → collection summary → progress tracking. It contains two God Functions (`process_document`, ~470 lines; `process_document_with_subdocuments`, ~500 lines) and a module-level mutable `processing_status` dict visible to multiple modules.

The file:
- Lives in `presentation/` but does infrastructure work (DB sessions, ORM commits, file I/O)
- Is impossible to unit-test — every test needs a full database and FAISS setup
- Has high change amplification risk — touching citation linking can break chunk persistence
- Mixes 8+ distinct responsibilities in one module

## Non-Goals
- Changing the processing logic itself — only re-organising existing code into modules
- Introducing new abstractions beyond what's needed for clean separation
- Changing the API contract (same `processing_status` structure, same progress events)
- Moving business rules into domain layer — this refactoring is structural only

## Architecture Decision

The new structure follows a **Pipeline + Strategy** pattern. Each processing stage becomes a Pipeline step with a clear input/output contract. The existing `UploadIngestionStrategy` (Strategy pattern, already in use) controls which stages run.

```
presentation/api/tasks.py          → thin orchestrator (~50 lines)
  └── infrastructure/repositories/processing/
      ├── structure_extractor.py   — extract_document_structure_skeleton wrapper
      ├── parent_extractor.py      — extract_parent_sections wrapper  
      ├── chunk_pipeline.py        — chunking + citation metadata (already exists, extend)
      ├── persistence_stage.py     — save chunks, parent sections, sub-documents
      ├── citation_linker.py       — add_citation_metadata_to_chunks, match_header_to_parents (header_matcher already extracted)
      ├── index_build_stage.py     — FAISS/BM25 index building
      ├── aggregate_build_stage.py — collection/account aggregate rebuild
      └── collection_summary_stage.py — update_collection_library_card
```

Progress tracking is already abstracted behind `UploadProgressTracker`. The `processing_status` dict stays in tasks.py but is only accessed through the tracker.

## Dependencies
- `header_matcher.py` already extracted (done in prior refactoring)
- No new domain interfaces needed — existing `Chunker`, `Embedder`, `BackgroundProcessor` are sufficient
- Each stage module depends on domain interfaces only, not on each other
