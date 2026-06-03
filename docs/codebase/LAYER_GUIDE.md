# Layer Guide

Kapsula follows **Clean Architecture** with strict dependency rules.

## Dependency Rule

```
PRESENTATION  →  APPLICATION  →  DOMAIN  ←  INFRASTRUCTURE
    ↓                ↓                       ↓
  Can import     Can import              Can import
  application   domain only             domain only
  + infra       (no infra!)
```

## Layer Map

```
kapsula/
├── presentation/          # API + MCP routes, tools
│   ├── api/               # FastAPI routes, background tasks
│   │   └── routes/        # accounts, collections, documents, search, health
│   └── mcp/               # FastMCP server, tools
│       └── tools/         # _db, _infra, _shared, accounts, collections,
│                          #   documents, export, search
├── startup/               # Composition root, DI wiring
├── core/
│   ├── application/       # Use cases, DTOs, selectors
│   │   ├── dto/           # Data transfer objects
│   │   └── use_cases/     # Business logic orchestration
│   └── domain/            # Pure business logic
│       ├── entities/      # Domain entities (canonical model)
│       ├── interfaces/    # ABCs and Protocols
│       ├── fusion/        # RRF, weighted fusion
│       └── *.py           # citation_matching, text_processing, quality_filter
└── infrastructure/        # Concrete implementations
    ├── data/              # ORM tables, connection, mappers, repositories
    ├── repositories/      # chunking, embedding, indexing, retrieval, reranking, processing
    └── external/llm/      # HuggingFace chat client
```

## Layer Rules

### DOMAIN (`core/domain/`)

**Can import:** `abc`, `typing`, `dataclasses`, `re`, `sqlalchemy.orm.Session` (interface parameter only)

**Cannot import:** Anything from `infrastructure`, `application`, or `presentation`.

**Contains:**
- Domain entities (`entities/*.py`) — pure dataclasses, never ORM models
- Interfaces (`interfaces/*.py`) — ABCs imported by use cases
- Pure functions — `citation_matching.py`, `text_processing.py`, `quality_filter.py`
- Fusion algorithms — `fusion/weighted_fusion.py`, `fusion/rrf_fusion.py`

**Exception:** `interfaces/index_manager.py` imports `dto/rebuild_result.py` — DTOs are data-only, acceptable.

### APPLICATION (`core/application/`)

**Can import:** Domain entities, domain interfaces, application DTOs, `sqlalchemy.orm.Session`.

**Cannot import:** Anything from `infrastructure` (no ORM models!) or `presentation`.

**Contains:**
- Use cases — orchestrate domain objects, depend on interfaces
- DTOs — data classes for use case inputs/outputs
- Selectors/strategies — collection routing, search strategies

### INFRASTRUCTURE (`infrastructure/`)

**Can import:** Domain interfaces (implements them), domain entities (maps to/from), ORM tables.

**Cannot import:** Application use cases, presentation modules.

**Contains:**
- Repository implementations — `sql_*_repository.py`
- Mappers — `mappers.py` (domain ↔ ORM conversion)
- ORM tables — `data/tables/*.py`
- Embedders, rerankers, retrievers, chunkers, index builders
- Background processors, progress trackers

### PRESENTATION (`presentation/`)

**Can import:** Domain entities, application use cases/DTOs, infrastructure ORM (for read queries).

**Pattern for ORM usage:**
```python
# Correct — aliased ORM import, explicit about what's infrastructure
from kapsula.infrastructure.data.tables.document import Document as OrmDocument

# Wrong — bare import confusing ORM with domain entity
from kapsula.infrastructure.data import Document
```

**Write operations use repositories:**
```python
from kapsula.infrastructure.repositories.data.sql_account_repository import SqlAccountRepository
_repo = SqlAccountRepository()
_repo.save(db, domain_account)
```

### STARTUP (`startup/`)

**Can import:** Everything (composition root).

**Contains:** DI factory functions (`create_*_use_case()`), app bootstrapping.

## Key Design Decisions

1. **Domain entities are the canonical model.** ORM models are only used inside infrastructure repositories. Mappers convert at the boundary.

2. **Use cases depend on interfaces, never concrete implementations.** This enables unit testing with mocks.

3. **Presentation uses repositories for writes, ORM for complex reads.** Full read-model separation is future work.

4. **One class per file.** Every class, interface, and DTO lives in its own file.
