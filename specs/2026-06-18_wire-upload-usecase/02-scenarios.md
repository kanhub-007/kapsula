# Scenarios — Wire UploadDocumentUseCase

---

### Scenario: Happy path — valid .md file upload succeeds
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a valid collection with collection_id="coll-123" exists
  When  POST /documents/upload is called with a valid .md file, collection_id="coll-123", ingestion_mode="indexed"
  Then  the UploadDocumentUseCase.execute() is called once
  And   a background task is queued for processing
  And   the response contains job_id, status="processing", ingestion_mode="indexed"

**Input table:**
| Field          | Type       | Example          | Constraints              |
|----------------|------------|------------------|--------------------------|
| collection_id  | str        | "coll-123"       | Must exist in DB         |
| file           | UploadFile | test.md (valid)  | .md extension, non-empty |
| max_tokens     | int        | 512              | Default 512              |
| ingestion_mode | str        | "indexed"        | fast\|indexed\|full       |

**Expected output:**
| Assertion                           | How to verify                            |
|-------------------------------------|------------------------------------------|
| response.status_code == 200         | HTTP response                            |
| response.job_id is not None         | UUID format                              |
| response.status == "processing"     | Response body                            |
| Document row exists with job_id     | Query DB                                 |
| processing_status[job_id] exists    | Read from status dict                    |
| Background task was queued          | Mock BackgroundTasks.add_task called     |

**Verify (Classical school, black-box):**
```python
fake_repo = InMemoryDocumentRepository()
fake_progress = InMemoryProgressTracker()
fake_processor = FakeBackgroundProcessor()
use_case = UploadDocumentUseCase(fake_processor, fake_repo, fake_progress)

with tempfile.NamedTemporaryFile(suffix=".md", mode="w") as f:
    f.write("# Test\nContent")
    f.flush()
    result = use_case.execute(db=fake_db, file_path=f.name, collection_id="coll-123", ingestion_mode="indexed")

assert result.job_id is not None
assert result.filename == os.path.basename(f.name)
assert fake_repo.saved_documents[0].status == "processing"
assert fake_processor.last_job_id == result.job_id
```

**Also test:**
- Non-.md file → raises ValueError
- Missing collection → raises ValueError
- Invalid ingestion_mode → raises ValueError
- Empty file → still processes (content may be empty but valid)

---

### Scenario: Route delegates validation to use case (no duplication)
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the route handler is called
  When  any validation fails (bad file extension, missing collection, etc.)
  Then  the HTTPException originates from the use case's ValueError
  And   the route does NOT contain its own file-extension or collection-existence checks

**Verify:**
```python
# Before: route had its own file extension check
# After: route calls use case, use case raises ValueError → route converts to HTTPException
from kapsula.presentation.api.routes.documents import upload_document
# Mock the use case to raise ValueError
with patch.object(use_case, 'execute', side_effect=ValueError("Only .md files accepted")):
    response = await upload_document(...)
    assert response.status_code == 400
```

---

### Scenario: Route still handles UploadFile → temp file conversion
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a FastAPI UploadFile is received
  When  the route calls UploadDocumentUseCase.execute()
  Then  the file content is written to a temp .md file
  And   the temp file path is passed to the use case
  And   the temp file is deleted after the use case returns (success or failure)

**Verify:**
```python
# Route creates temp file, passes path, cleans up
# Use case reads from path
fake_use_case = Mock()
fake_use_case.execute.return_value = UploadDocumentResult(...)
with patch("tempfile.NamedTemporaryFile") as mock_temp:
    await upload_document(file=mock_upload_file, ...)
    mock_temp.return_value.__enter__.return_value.name.assert_called()
    # Verify temp file was cleaned up
```

---

### Scenario: UploadJobManager progress tracking is still created
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given a successful upload
  When  the use case completes
  Then  UploadJobManager.create() is called with job_id, filename, collection info
  And   processing_status[job_id] shows status="processing", stage="queued"

**Verify:**
```python
job = UploadJobManager().get(result.job_id)
assert job["status"] == "processing"
assert job["filename"] == expected_filename
```

---

### Scenario: Background task receives the same parameters as before
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given an upload is accepted
  When  the background task is queued
  Then  process_document_with_subdocuments is called with the same args as before refactoring
  And   the args include job_id, markdown_content, max_tokens, db_session, ingestion_mode

**Verify:**
```python
# Mock BackgroundTasks.add_task
mock_bg = Mock()
await upload_document(background_tasks=mock_bg, ...)
call_args = mock_bg.add_task.call_args
assert call_args[0][0] == process_document_with_subdocuments  # same function
assert call_args[1]["job_id"] == result.job_id
assert call_args[1]["ingestion_mode"] == "indexed"
```
