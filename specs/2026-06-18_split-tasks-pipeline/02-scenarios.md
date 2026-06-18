# Scenarios — Split tasks.py Pipeline

---

### Scenario: Process document (single-index path) completes end-to-end
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a markdown file has been uploaded and a Document record exists with job_id="abc-123"
  When  process_document is called with ingestion_mode="indexed"
  Then  all stages execute in sequence and the document status is "completed"
  And   the processing_status dict contains progress=100, stage="completed"

**Input table:**
| Field           | Type   | Example           | Constraints              |
|-----------------|--------|-------------------|--------------------------|
| job_id          | str    | "abc-123"         | Valid GUID, exists in DB |
| markdown_content| str    | "# Title\ncontent"| Non-empty                |
| max_tokens      | int    | 512               | > 0                     |
| db              | Session| SQLAlchemy session | Open session             |
| ingestion_mode  | str    | "indexed"         | fast\|indexed\|full       |

**Expected output / state change:**
| Assertion                                | How to verify                              |
|------------------------------------------|--------------------------------------------|
| document.status == "completed"           | Query Document table by job_id             |
| Chunk rows exist for document_id         | Query Chunk table                          |
| processing_status["abc-123"]["progress"] == 100 | Read from processing_status dict     |
| Same output as before refactoring        | Compare stdout/logs with baseline          |

**Verify (Classical school, black-box):**
```python
fake_db = InMemorySession()
fake_embedder = FakeEmbedder()
fake_status = {}

pipeline = DocumentPipeline(
    structure_extractor=FakeStructureExtractor(),
    parent_extractor=FakeParentExtractor(),
    chunker=FakeChunker(),
    persist=PersistenceStage(),
    index_builder=FakeIndexBuilder(fake_embedder),
    progress=UploadProgressTracker(fake_status, null_logger),
)
pipeline.execute(job_id="abc-123", content="# Test", max_tokens=512, db=fake_db)
assert fake_status["abc-123"]["status"] == "completed"
assert fake_db.count(Chunk) == fake_chunker.chunk_count
```

**Also test:**
- Empty markdown content → raises ValueError early (structure extractor fails)
- ingestion_mode="fast" → index building stage is skipped, status still "completed"
- Database error during persistence → document.status == "failed", processing_status updated
- Sub-document path (`process_document_with_subdocuments`) → all same stages, plus sub-doc creation

---

### Scenario: Each stage module is independently testable
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a CitationLinker module extracted from tasks.py
  When  I write a test importing only CitationLinker
  Then  the test does NOT import tasks.py, FAISS, SQLAlchemy, or any other stage

**Input table:**
| Stage module                           | Dependencies allowed                  |
|----------------------------------------|---------------------------------------|
| structure_extractor.py                 | markdown_chunker (already infra)      |
| parent_extractor.py                    | chunking utilities (already infra)    |
| citation_linker.py                     | citation_matching (domain), header_matcher (infra) |
| persistence_stage.py                   | ORM tables, Session                   |
| index_build_stage.py                   | Embedder, DocumentIndexBuilder (infra)|
| aggregate_build_stage.py               | AggregateIndexBuilder (infra)         |
| collection_summary_stage.py            | CollectionSummaryGenerator (app), ChatClient |

**Verify:**
```python
# Test citation linker without any DB
from kapsula.infrastructure.repositories.processing.citation_linker import add_citation_metadata_to_chunks
chunks = [{"content": "hello world", "metadata": {"chunk_index": 0}}]
result = add_citation_metadata_to_chunks(chunks, parent_sections={}, markdown_content="hello world")
assert "citation" in result[0]["metadata"]
```

**Also test:**
- Each stage module has a single public function or class
- No stage imports another stage (only domains/infrastructure interfaces)

---

### Scenario: Existing progress tracking contract is preserved
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given an external caller polls processing_status["abc-123"] during a running upload
  When  any stage updates progress
  Then  the dict has the exact same keys as before refactoring: status, progress, stage, message

**Verify:**
```python
fake_status = {}
progress = UploadProgressTracker(fake_status, null_logger)
progress.set("abc-123", status="processing", progress=50, stage="chunking", message="...")
assert fake_status["abc-123"] == {
    "status": "processing", "progress": 50, "stage": "chunking", "message": "..."
}
```

---

### Scenario: UploadProgressTracker logging is preserved
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given _upload_progress.log_stage is called by each stage
  When  processing completes
  Then  log output contains per-stage timing messages identical to before refactoring

**Verify:**
- Capture log output and compare pattern of `"completed in X.XXXs"` messages
- Stage names match old stage values: "extracting_structure", "chunking", "building_indexes", etc.

---

### Scenario: Old module-level imports still work for migration
**Priority:** Could
**Slice:** 3

**Gherkin:**
  Given external code imports `from kapsula.presentation.api.tasks import process_document`
  When  the refactoring is deployed
  Then  the import still works (re-export from new location)
  And   a deprecation warning is emitted

**Verify:**
```python
import warnings
with warnings.catch_warnings(record=True) as w:
    from kapsula.presentation.api.tasks import process_document
    assert len(w) >= 1
    assert "deprecated" in str(w[0].message).lower()
```
