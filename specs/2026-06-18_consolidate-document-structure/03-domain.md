# Domain Model — Consolidate Document Structure

## Modified Entities

None. No new domain entities are created.

## New Shared Helper (Presentation Layer)

### build_document_structure_from_subdocs
`kapsula/presentation/shared/document_structure_builder.py`
```python
def build_document_structure_from_subdocs(
    subdocs: list[SubDocument], db: Session
) -> list[dict]:
    """Build structure list from ORM SubDocument objects.
    
    Returns list of {"subdocument_name": str, "sections": [{"level": str, "title": str}]}
    """
```

### build_document_structure_from_document
```python
def build_document_structure_from_document(
    document_id: int, fallback_name: str, db: Session, limit: int = 20,
) -> list[dict]:
    """Build structure list from a single-index document's library cards.
    
    Returns single-element list or empty list.
    """
```

## Output Format (Contract with QueryPlanner)

The `document_structure` list is consumed by `QueryPlanner.plan_document_search()`. Format MUST be:
```python
[
    {
        "subdocument_name": "Introduction to ML",  # str
        "sections": [
            {"level": "level_1", "title": "Machine Learning Basics"},
            {"level": "level_2", "title": "Supervised Learning"},
            {"level": "level_3", "title": "Linear Regression"},
        ]
    },
    ...
]
```

The `level` values come directly from `LibraryCard.level` (stored as "level_1", "level_2", "level_3"). The `QueryPlanner` expects these exact strings.

## Entity vs ORM Separation
This helper lives in `presentation/shared/` because it uses ORM models directly (CQRS-lite read exception for complex read projections). It queries `LibraryCard` ORM table and returns plain dicts — no domain entities are involved.
