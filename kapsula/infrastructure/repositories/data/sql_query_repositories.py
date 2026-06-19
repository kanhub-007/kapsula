"""SQLAlchemy-backed query repositories (read-only).

Backward-compat re-export facade. Each SQL repository now lives in its own
file (closes H2 — one-class-per-file rule). New code should import from the
specific module; this module is kept so existing imports keep working.
"""

# ruff: noqa: F401  — re-export facade

from kapsula.infrastructure.repositories.data.sql_chunk_repository import (
    SqlChunkRepository,
)
from kapsula.infrastructure.repositories.data.sql_library_card_repository import (
    SqlLibraryCardRepository,
)
from kapsula.infrastructure.repositories.data.sql_sub_document_repository import (
    SqlSubDocumentRepository,
)
