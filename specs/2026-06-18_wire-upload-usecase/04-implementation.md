# Implementation Guide — Wire UploadDocumentUseCase

> **Prerequisites:** Spec 5 (fix-repository-temporal-coupling) MUST be done first.
> If `save_document` return type changes, Step 1 below uses `doc = self._document_repository.save_document(db, doc)`.
> **Rollback:** `git checkout kapsula/presentation/api/routes/documents.py kapsula/core/application/use_cases/upload_document.py`

---

### Step 1: Add `execute_from_content` to UploadDocumentUseCase
**File:** `kapsula/core/application/use_cases/upload_document.py`

The current `execute()` takes a file path and reads it with `Path.read_text(encoding="utf-8")`. The route receives `UploadFile.read()` which returns `bytes`. Add a method that bridges the gap:

```python
def execute_from_content(
    self,
    db,
    content_bytes: bytes,
    filename: str,
    collection_id: str,
    max_tokens: int = 512,
    ingestion_mode: str = "indexed",
    client_ip: str = "127.0.0.1",
) -> UploadDocumentResult:
    """Execute upload from raw content bytes (for HTTP upload routes).
    
    Writes content to a temp file, delegates to execute(), cleans up.
    """
    import tempfile
    suffix = Path(filename).suffix if Path(filename).suffix else ".md"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="wb") as tmp:
        tmp.write(content_bytes)
        tmp_path = tmp.name
    try:
        return self.execute(db, tmp_path, collection_id, max_tokens, ingestion_mode)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
```

**Critical — bytes vs str:** `UploadFile.read()` returns `bytes`. The temp file must be opened in `"wb"` mode. The existing `execute()` method uses `Path.read_text(encoding="utf-8")` which handles the file reading correctly. Do NOT try to decode bytes to str first — let `execute()` read the file.

**Critical — client_ip:** The old route used `request.client.host` for `client_ip`. The new `execute()` method gets it from `Path.file_path` — but the use case already sets `ip_address="127.0.0.1"` in the Document constructor. If you need to preserve the real client IP, pass it through:

Option: Add `ip_address` parameter to `execute()` and `execute_from_content()`. Or keep it simple — the field is informational and `127.0.0.1` is acceptable for local dev. For production, extend later.

**Verify:** Unit test with in-memory repos.
**Common mistake:** Not using `delete=False` and `mode="wb"` — the context manager would delete the file before `execute()` reads it, and `"w"` mode on bytes raises TypeError.

---

### Step 2: Update Route to Use the Use Case
**File:** `kapsula/presentation/api/routes/documents.py`

Replace the inline validation + ORM logic (~50 lines) with:

```python
from kapsula.startup import create_upload_document_use_case

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    request: Request,
    collection_id: str,
    file: UploadFile = File(...),
    max_tokens: int = 512,
    ingestion_mode: str = "indexed",
    db: Session = Depends(get_db),
):
    content = await file.read()
    
    try:
        use_case = create_upload_document_use_case()
        result = use_case.execute_from_content(
            db=db,
            content=content,
            filename=file.filename or "upload.md",
            collection_id=collection_id,
            max_tokens=max_tokens,
            ingestion_mode=ingestion_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Background processing (FastAPI-specific, stays in route)
    background_tasks.add_task(
        process_document_with_subdocuments,
        job_id=result.job_id,
        markdown_content=content.decode("utf-8"),
        max_tokens=max_tokens,
        db=SessionLocal(),
        ingestion_mode=result.ingestion_mode,
    )

    return UploadResponse(
        job_id=result.job_id,
        collection_id=collection_id,
        status="processing",
        message=f"Document uploaded successfully. Processing started with ingestion_mode={result.ingestion_mode}.",
        ingestion_mode=result.ingestion_mode,
    )
```

**Verify:** `pytest tests/ -k upload`
**Common mistake:** The `UploadFile.filename` can be None (Starlette quirk) — guard with `or "upload.md"`.

---

### Step 3: Remove Duplicate Validation from Route
**File:** `kapsula/presentation/api/routes/documents.py`

Remove:
- `UploadIngestionMode.normalize(ingestion_mode)` — use case does this
- `db.query(OrmCollection).filter(...)` collection check — use case does this
- `file.filename.endswith(".md")` check — use case does this
- Direct `OrmDocument(...)` creation + `db.add()` — use case does this via repository

**Verify:** Run existing integration tests — they should still pass with identical responses.
**Common mistake:** The route currently calls `UploadJobManager().create()` — the use case calls `ProgressTracker.register_job()` which should have the same effect. Verify `get_processing_status(job_id)` still works.

---

### Step 4: Ensure UploadJobManager.create() Is Called
The `UploadDocumentUseCase` currently calls `self._progress_tracker.register_job()`. The `InMemoryProgressTracker` updates `processing_status` but does NOT call `UploadJobManager.create()` (which persists to DB). 

Option A: Have the route call `UploadJobManager().create()` after the use case.
Option B: Have `InMemoryProgressTracker.register_job()` also create the `UploadJob` DB row.

Choose Option A (simpler, keeps tracker pure):

```python
# After use_case.execute():
UploadJobManager().create(
    job_id=result.job_id,
    filename=result.filename,
    collection_id=collection.id,
    collection_name=result.collection_name,
    ingestion_mode=result.ingestion_mode,
)
```

**Verify:** After upload, `GET /documents/progress/{job_id}` returns the persisted job.
**Common mistake:** Not passing `collection.id` (internal ID) vs `collection_id` (GUID).

---

### Step 5: Update Existing Tests
**File:** `tests/test_mcp/test_integration.py`

If tests directly create `OrmDocument` records or mock `processing_status`, update them to go through the use case or mock the use case at the route level.

**Verify:** `pytest tests/` — all tests pass.
