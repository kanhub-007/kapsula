# Domain Model — Wire UploadDocumentUseCase

## Modified Entities

### UploadDocumentResult (DTO — unchanged)
`core/application/dto/upload_document_result.py`
```python
@dataclass
class UploadDocumentResult:
    job_id: str
    filename: str
    collection_name: str
    ingestion_mode: str
```
No changes. The route maps this to `UploadResponse` (API DTO).

## Modified Interfaces

### UploadDocumentUseCase
`core/application/use_cases/upload_document.py`

New method added to existing class:
```python
def execute_from_content(
    self,
    db: Any,
    content_bytes: bytes,
    filename: str,
    collection_id: str,
    max_tokens: int = 512,
    ingestion_mode: str = "indexed",
    client_ip: str = "127.0.0.1",
) -> UploadDocumentResult: ...
```

Existing `execute()` method is unchanged:
```python
def execute(
    self,
    db: Any,
    file_path: str,
    collection_id: str,
    max_tokens: int = 512,
    ingestion_mode: str = "indexed",
) -> UploadDocumentResult: ...
```

## Dependencies
- `DocumentRepository.save_document()` — returns `Document` (after Spec 5 fix)
- `BackgroundProcessor.start_processing()` — unchanged
- `ProgressTracker.register_job()` — unchanged

## Entity vs ORM Separation
The route currently creates `OrmDocument` directly. After wiring, the route only creates `UploadDocumentResult` (DTO) and `UploadResponse` (API model). Domain `Document` is created inside the use case.
