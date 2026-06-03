# AGENTS.md — Kapsula Development Guide

> **For AI coding assistants and human developers.** This document describes how
> to work in this codebase — architecture, patterns, conventions, and rules.

---

## Project Identity

Kapsula is a **structured knowledge memory system** for AI assistants. It ingests
documents, builds hybrid search indexes (FAISS + BM25), expands context via Library
Cards, and serves results through a FastAPI REST API and an MCP server.

---

## Architecture Skeleton

Kapsula follows **Clean Architecture** with four layers plus a composition root.
Dependencies flow inward. Outer layers know about inner layers; inner layers
know nothing about outer layers.

```
┌──────────────────────────────────────────────────────┐
│  presentation/     FastAPI routes, MCP tools          │  ← adapters
│                    Can import: application, domain,   │
│                    infrastructure (ORM for reads)     │
├──────────────────────────────────────────────────────┤
│  startup/          Composition root, DI factories     │  ← wiring
│                    Can import: EVERYTHING             │
├──────────────────────────────────────────────────────┤
│  core/application/ Use cases, DTOs, selectors         │  ← orchestration
│                    Can import: domain ONLY            │
│                    CANNOT import: infrastructure,     │
│                    presentation                       │
├──────────────────────────────────────────────────────┤
│  core/domain/      Entities, interfaces, pure logic   │  ← innermost
│                    Can import: stdlib, typing, abc,   │
│                    dataclasses, numpy (embeddings)    │
│                    CANNOT import: anything else       │
├──────────────────────────────────────────────────────┤
│  infrastructure/   ORM tables, repositories, FAISS,   │  ← I/O
│                    BM25, embedders, chunkers, LLM     │
│                    Can import: domain (implements     │
│                    interfaces)                        │
│                    CANNOT import: application,        │
│                    presentation                       │
└──────────────────────────────────────────────────────┘
```

### Layer Purposes

| Layer | Purpose | What Goes Here |
|-------|---------|---------------|
| `core/domain/` | Pure business logic — no frameworks | Entities (dataclasses), interfaces (ABCs/Protocols), fusion algorithms, quality filters, text processing, citation matching |
| `core/application/` | Orchestration — wires domain objects together | Use cases, DTOs (data transfer objects), selectors, strategies, query planner |
| `infrastructure/` | Concrete implementations of domain interfaces | ORM tables, SQL repositories, mappers, embedders, retrievers (FAISS/BM25), rerankers, chunkers, LLM clients, background processors, index builders |
| `presentation/` | Adapters to the outside world | FastAPI routes and models, MCP server and tools, search presenters, upload job management |
| `startup/` | Composition root — wires everything together | DI factory functions, `bootstrap()`, `create_app()`, `create_server()` |

### Key Rule: Domain → Application Boundary

Application use cases depend on **domain interfaces** (ABCs/Protocols), never on
concrete infrastructure classes. This is the most important rule in the codebase.

```python
# ✅ CORRECT — use case depends on abstract interface
class DeleteDocumentUseCase:
    def __init__(self, index_manager: IndexManager, document_repository: DocumentRepository):
        ...

# ❌ WRONG — use case depends on concrete implementation
class DeleteDocumentUseCase:
    def __init__(self, file_system_index_manager: FileSystemIndexManager, ...):
        ...
```

Concrete implementations are wired in via the composition root (the `startup/` layer).

---

## Design Patterns — Must Apply Strictly

These patterns are **mandatory** when applicable. Code that ignores them will be
flagged in review.

### 1. Dependency Injection (Constructor Injection)

All dependencies are passed through the constructor. No service locators, no
singleton imports, no global state.

```python
# ✅ CORRECT
class HybridSearcher:
    def __init__(self, retriever: Retriever, fusion: Fusion, reranker: Reranker):
        self._retriever = retriever
        self._fusion = fusion
        self._reranker = reranker

# ❌ WRONG
class HybridSearcher:
    def __init__(self):
        self._retriever = DenseRetriever()  # hardwired concrete class
```

**Exception:** MCP tool modules may use module-level singletons for repositories
and cached infrastructure (embedders, chat clients) because FastMCP tool
registration creates per-module state. These are created in `startup/` and
referenced via `_shared.py` helpers with lazy initialization. This is acceptable
because MCP tools live in the presentation layer (outermost), not in application
or domain.

### 2. Repository Pattern

All database access goes through repository classes that implement domain
interfaces. Repositories take a domain entity, convert to ORM via mappers,
persist, and convert back.

```
Domain Entity  ←→  Mapper  ←→  ORM Model  ←→  Database
```

```python
# Interface (in core/domain/interfaces/)
class AccountRepository(ABC):
    @abstractmethod
    def save(self, db: Session, account: Account) -> None: ...
    @abstractmethod
    def find_by_account_id(self, db: Session, account_id: str) -> Account | None: ...

# Implementation (in infrastructure/repositories/data/)
class SqlAccountRepository(AccountRepository):
    def save(self, db: Session, account: Account) -> None:
        orm_account = account_to_orm(account)  # mapper
        db.add(orm_account)
        db.commit()
```

**Presentation layer exception:** Complex read queries (searches, aggregations)
may use ORM directly in presentation tools. Write operations MUST use
repositories. This is pragmatic — full CQRS is deferred.

### 3. Strategy Pattern

When behavior varies, define an interface and multiple implementations. The
caller selects the strategy; the use case doesn't care which one.

**Examples in the codebase:**
- `Fusion` interface → `RRFFusion`, `WeightedFusion`
- `UploadIngestionStrategy` → `FastUploadIngestionStrategy`, `IndexedUploadIngestionStrategy`, `FullUploadIngestionStrategy`
- `CollectionRoutingStrategy` → `FastCollectionRoutingStrategy`, `LLMCollectionRoutingStrategy`, `AutoCollectionRoutingStrategy`
- `ElementHandler` → `CodeHandler`, `TableHandler`, `ListHandler`, `TextHandler`, `TitleHandler`

### 4. Factory Pattern (Composition Root)

Complex object graphs are assembled in the `startup/` layer using factory
functions. Factories return fully-wired dependencies with all interfaces
satisfied.

```python
# startup/hybrid_searcher_factory.py
def create_multi_index_searcher(db: Session) -> MultiIndexSearcher:
    embedder = create_embedder()
    dense_retriever = DenseRetriever(embedder)
    sparse_retriever = SparseRetriever()
    fusion = WeightedFusion()
    reranker = create_reranker()
    index_manager = FileSystemIndexManager()
    search_data_access = SqlSearchDataAccess()
    return MultiIndexSearcher(
        dense_retriever, sparse_retriever, fusion, reranker,
        index_manager, search_data_access,
    )
```

**Rule:** Never construct complex objects inline in use cases or tools.
Always delegate to a factory.

### 5. DTO (Data Transfer Object)

Data crossing layer boundaries (use case input/output) uses dedicated DTO
classes — pure dataclasses with no behavior, no ORM, no domain logic.

```python
# core/application/dto/delete_document_result.py
@dataclass
class DeleteDocumentResult:
    job_id: str
    filename: str
    collection_name: str
    chunks_deleted: int
    rebuild: RebuildResult | None = None
    error: str | None = None
```

**DTOs live in:** `core/application/dto/` (shared by application and presentation).
API-specific DTOs live in `presentation/api/dto/` (Pydantic models for FastAPI).

### 6. Observer / Background Processing

Long-running operations (document processing, index building) are dispatched to
a background processor interface. The use case queues work and returns immediately;
the caller polls progress.

```python
# Interface
class BackgroundProcessor(ABC):
    @abstractmethod
    def submit(self, task: Callable, *args, **kwargs) -> None: ...

# Concrete
class ThreadPoolBackgroundProcessor(BackgroundProcessor): ...
```

### 7. Facade (Search Presenters)

Complex multi-step operations (hybrid search → fusion → rerank → context expansion)
are wrapped behind presenter/facade classes that expose a single clean method.

```python
# presentation/mcp/search_presenter.py
def format_search_results(query, results, scope) -> str: ...
# presentation/api/search_presenter.py
class SearchPresenter:
    def present(self, results) -> SearchResponse: ...
```

### Patterns to AVOID

| Anti-pattern | Why it's banned |
|-------------|-----------------|
| **Singleton** (global state) | Makes testing impossible, violates DI. Use factory + caching if needed. |
| **Service Locator** | Hides dependencies, makes code untestable. Use constructor injection. |
| **God Class** | Single class doing too many things. Split by responsibility. |
| **Anemic Domain Model** | Entities with only getters/setters, logic in services. Put domain logic in entities or domain services. |
| **Inheritance for code reuse** | Prefer composition. Interfaces use ABC/Protocol, not deep class hierarchies. |

---

## One Class Per File — Strict Rule

Every class, interface (ABC/Protocol), DTO, entity, enum, and strategy lives in
its own file. No exceptions.

**File naming:** `snake_case.py` matching the class name.

```python
# ✅ CORRECT
kapsula/core/domain/interfaces/embedder.py        → class Embedder(Protocol)
kapsula/core/domain/interfaces/retriever.py       → class Retriever(ABC)
kapsula/core/application/dto/rebuild_result.py    → class RebuildResult
kapsula/core/domain/fusion/rrf_fusion.py          → class RRFFusion
kapsula/infrastructure/data/tables/account.py     → class Account (ORM)
```

```python
# ❌ WRONG — multiple classes in one file
kapsula/core/domain/interfaces/search_interfaces.py
    → class Embedder, class Retriever, class Reranker  # NO
```

**Exceptions to this rule:**
- `__init__.py` files (package declarations, re-exports)
- File-level helper functions tightly coupled to the single class in the file
- Protocol helper types used only by the one class in the file (e.g., `HasAccountId`
  in `index_manager.py`)

---

## Coding Conventions

### Imports

```python
# 1. Standard library
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

# 2. Third-party
from sqlalchemy.orm import Session
import numpy as np

# 3. Internal — always absolute imports from kapsula root
from kapsula.core.domain.entities.account import Account as DomainAccount
from kapsula.infrastructure.data.tables.account import Account as OrmAccount

# Domain entity vs ORM model disambiguation:
#   DomainAccount / OrmAccount  (preferred)
#   Account (domain) / OrmAccount (infrastructure alias)
# Never import ORM models as bare names — always alias.
```

### Naming

| Thing | Convention | Example |
|-------|-----------|---------|
| Classes | PascalCase | `DeleteDocumentUseCase` |
| Interfaces (ABC) | PascalCase, no `I` prefix | `IndexManager`, `Embedder` |
| Protocols | PascalCase | `Embedder`, `HasAccountId` |
| Functions/Methods | snake_case | `find_by_account_id()` |
| Variables | snake_case | `chunks_deleted` |
| Constants | UPPER_SNAKE | `MAX_CHUNK_SIZE` |
| Private members | `_prefix` | `self._index_manager` |
| File names | snake_case | `delete_document.py` |

### Type Hints

All public methods and functions MUST have type hints. Use `| None` not `Optional`.

```python
def execute(self, db: Session, job_id: str) -> DeleteDocumentResult:
    ...

def find_by_account_id(self, db: Session, account_id: str) -> Account | None:
    ...
```

### Docstrings

All public classes and methods have docstrings. Format: triple-quote on its own line,
first line is a summary, blank line, then details.

```python
class DeleteDocumentUseCase:
    """Soft-deletes a document: archives it, cascade-deletes related records,
    removes index files, and rebuilds aggregate indexes."""

    def execute(self, db: Session, job_id: str) -> DeleteDocumentResult:
        """Execute the delete operation.

        Args:
            db: Database session.
            job_id: The job_id (GUID) of the document to delete.

        Returns:
            DeleteDocumentResult with details about the operation.

        Raises:
            ValueError: If the document is not found.
        """
```

### Domain Entity vs ORM Model

Domain entities are dataclasses in `core/domain/entities/`. ORM models are
SQLAlchemy-mapped classes in `infrastructure/data/tables/`. They are NEVER the
same class. Conversion happens in `infrastructure/repositories/data/mappers.py`.

```python
# Domain entity — pure Python, no ORM
@dataclass
class Account:
    id: int | None = None
    account_id: str = ""
    name: str = ""
    ...

# ORM model — SQLAlchemy table mapping
class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True)
    account_id = Column(String, unique=True)
    name = Column(String)
    ...
```

---

## How to Add a Feature

Follow this sequence when adding new functionality:

### 1. Define the domain interface (if new capability)

```
kapsula/core/domain/interfaces/my_new_thing.py
  → class MyNewThing(ABC):
        @abstractmethod
        def do_something(self, ...) -> ...: ...
```

### 2. Define domain entities (if new data)

```
kapsula/core/domain/entities/my_entity.py
  → @dataclass class MyEntity: ...
```

### 3. Define DTOs (if data crosses boundaries)

```
kapsula/core/application/dto/my_result.py
  → @dataclass class MyResult: ...
```

### 4. Define the use case

```
kapsula/core/application/use_cases/my_use_case.py
  → class MyUseCase:  # depends on domain interfaces only
```

### 5. Implement the infrastructure

```
kapsula/infrastructure/data/tables/my_entity.py       # ORM table
kapsula/infrastructure/repositories/data/mappers.py   # Add mapper functions
kapsula/infrastructure/repositories/data/sql_my_repository.py  # Repository impl
kapsula/infrastructure/repositories/my_thing.py       # Concrete implementation
```

### 6. Wire it up (composition root)

```
kapsula/startup/my_factory.py
  → def create_my_use_case() -> MyUseCase: ...
```

### 7. Expose it (presentation)

```
kapsula/presentation/mcp/tools/my_tool.py    # MCP tool
kapsula/presentation/api/routes/my_route.py  # REST endpoint (if needed)
```

### 8. Register it

```
kapsula/presentation/mcp/tools/__init__.py   # register_my_tools(mcp)
kapsula/startup/mcp.py or api.py             # Wire into server (if needed)
```

---

## Linting & Formatting

This project uses **ruff** for linting and **black** for formatting. Run both before committing:

```bash
# Format
black kapsula/ tests/

# Lint + auto-fix
ruff check kapsula/ tests/ --fix

# Lint only (no changes)
ruff check kapsula/ tests/
```

**Rules:**
- All code must pass `ruff check` with zero errors before commit.
- All code must be formatted with `black` (line length 88, default).
- CI will reject code that fails either tool.
- Run both from the project root.

---

## Testing

Tests live in `tests/`, mirroring the source structure:

```
tests/
├── test_mcp/
│   ├── test_db.py
│   ├── test_integration.py
│   └── test_server.py
└── (add test_domain/, test_application/, test_infrastructure/ as needed)
```

- **Domain tests:** Pure unit tests, no DB, no filesystem. Mock interfaces.
- **Application tests:** Use case tests with mocked infrastructure interfaces.
- **Infrastructure tests:** Integration tests with real SQLite (in-memory) and
  real FAISS indexes on temporary files.
- **MCP tests:** Full stack tests — create app, call tools, verify results.

Run with: `pytest tests/`

---

## Key Files to Know

| File | Purpose |
|------|---------|
| `kapsula/startup/__init__.py` | `bootstrap()` — DB init, default account creation |
| `kapsula/startup/api.py` | FastAPI `create_app()` with lifespan |
| `kapsula/startup/mcp.py` | FastMCP `create_server()` with tool registration |
| `kapsula/infrastructure/data/connection.py` | SQLAlchemy engine + session factory |
| `kapsula/infrastructure/repositories/data/mappers.py` | Domain ↔ ORM converters |
| `kapsula/infrastructure/logging_config.py` | `get_logger()` helper |
| `kapsula/presentation/mcp/tools/_shared.py` | Shared infrastructure access for tools |
| `kapsula/presentation/mcp/tools/_db.py` | DB session helpers for tools |
| `kapsula/presentation/mcp/tools/_infra.py` | Cached infrastructure singletons |

---

Implementation plans live in `docs/plans/`. Read the relevant plan before starting work on a feature area.
