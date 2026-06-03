# Domain Entities

Canonical domain models. Pure dataclasses — no ORM, no framework dependencies.

Location: `doc_search/core/domain/entities/`

## Entity Reference

### Account

```python
@dataclass
class Account:
    id: int | None = None
    account_id: str = ""           # GUID
    name: str = ""
    created_at: datetime | None = None
    ip_address: str = ""
    collections: list[Collection]  # navigation (populated by repository)
```

### Collection

```python
@dataclass
class Collection:
    id: int | None = None
    collection_id: str = ""        # GUID
    account_id: int | None = None
    name: str = ""
    logo_filename: str | None = None
    created_at: datetime | None = None
    ip_address: str = ""
    account: Optional[Account]      # navigation
    documents: list[Document]       # navigation
```

### Document

```python
@dataclass
class Document:
    id: int | None = None
    job_id: str = ""               # GUID — used for delete/lookup
    collection_id: int | None = None
    filename: str = ""
    size: int = 0
    created_at: datetime | None = None
    ip_address: str = ""
    duration: float | None = None
    content: str = ""
    status: str = "processing"     # processing | completed | failed | archived
    doc_state: str = "active"      # active | archived
    faiss_index_path: str | None = None
    bm25_index_path: str | None = None
    collection: Optional[Collection]  # navigation
    chunks: list[Chunk]               # navigation
    sub_documents: list[SubDocument]  # navigation
```

### Chunk

```python
@dataclass
class Chunk:
    id: int | None = None
    document_id: int | None = None
    sub_document_id: int | None = None
    content: str = ""
    chunk_index: int = 0
    token_count: int | None = None
    chunk_metadata: str | None = None  # JSON string
    created_at: datetime | None = None
```

### SubDocument

```python
@dataclass
class SubDocument:
    id: int | None = None
    document_id: int | None = None
    breadcrumb_key: str = ""       # H2 heading text
    breadcrumb_level: int = 0      # heading depth
    faiss_index_path: str | None = None
    bm25_index_path: str | None = None
    page_count: int = 0
    created_at: datetime | None = None
```

### SubDocumentPage

```python
@dataclass
class SubDocumentPage:
    id: int | None = None
    sub_document_id: int | None = None
    page_title: str = ""
    breadcrumb_full: str = ""      # full H1/H2/H3 path
    content_hash: str | None = None
    created_at: datetime | None = None
```

### LibraryCard

```python
@dataclass
class LibraryCard:
    id: int | None = None
    collection_id: int | None = None
    document_id: int | None = None
    sub_document_id: int | None = None
    doc_id: str = ""               # hash identifier
    level: str = ""                # "collection" | "document" | "subdocument" | "level_1" | "level_2" | "level_3"
    title: str = ""
    content: str = ""
    extra_metadata: str | None = None  # JSON string
    created_at: datetime | None = None
```

### DocumentStructure

```python
@dataclass
class DocumentStructure:
    id: int | None = None
    document_id: int | None = None
    skeleton_structure: str = ""   # markdown heading skeleton
    created_at: datetime | None = None
```

## Design Notes

- Domain entities are the **canonical model**. ORM tables mirror them but are only used inside infrastructure repositories.
- **Mappers** (`infrastructure/repositories/data/mappers.py`) convert between domain entities and ORM models.
- Navigation properties (`collection`, `chunks`, `documents`, etc.) are populated by repositories, not by ORM lazy-loading.
- Flat mapping only — nested relationships are not eagerly loaded to avoid cycles.
