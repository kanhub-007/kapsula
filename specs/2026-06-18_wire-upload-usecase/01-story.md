# Wire UploadDocumentUseCase in Documents Route

## User Story
As a developer, I want the `POST /documents/upload` route to delegate to `UploadDocumentUseCase` instead of duplicating validation and persistence logic inline, so that business rules are enforced in one place and the route is a thin adapter.

## Context

The `upload_document` route in `routes/documents.py` currently:
1. Validates ingestion mode (duplicate of UploadDocumentUseCase)
2. Validates file extension (duplicate)
3. Queries collection directly via ORM (bypasses DocumentRepository)
4. Creates ORM Document and calls `db.add()`/`db.commit()` directly (bypasses `DocumentRepository.save_document()`)
5. Manually creates `UploadJobManager` progress entry
6. Manually dispatches background task

Meanwhile, `UploadDocumentUseCase` (in `core/application/use_cases/upload_document.py`) already:
1. Normalises and validates ingestion mode
2. Validates file path and extension
3. Validates collection existence via DocumentRepository
4. Creates domain Document entity and persists via DocumentRepository
5. Registers progress via ProgressTracker
6. Starts background processing via BackgroundProcessor

The route should be a thin adapter: parse HTTP request → call use case → return HTTP response.

## Non-Goals
- Changing the behaviour of validation, persistence, or progress tracking
- Changing the API contract (same request/response models)
- Moving the background task dispatch pattern — `BackgroundTasks` is a FastAPI concern
- Changing the `processing_status` dict or `UploadJobManager` persistence

## Architecture Decision

The route will use the existing `UploadDocumentUseCase` for validation + domain logic, and keep `BackgroundTasks.add_task()` at the route level (since `BackgroundTasks` is FastAPI-specific). The UploadJobManager progress tracking will be moved into the `InMemoryProgressTracker` implementation (or the use case will accept a progress_tracker adapter).

Since `UploadDocumentUseCase.execute()` takes a file path (not raw content), and the route receives `UploadFile`, the route will:
1. Save uploaded file content to a temp file
2. Call `use_case.execute(db, temp_path, collection_id, max_tokens, ingestion_mode)`
3. Delete temp file
4. Return `UploadResponse` from the use case result DTO

Alternatively, add an `execute_from_content()` method to the use case that accepts raw bytes/str content.
