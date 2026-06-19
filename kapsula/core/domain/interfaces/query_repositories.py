"""Repository interfaces for read-model queries (chunks, cards, subdocs, jobs).

Backward-compat re-export facade. Each interface now lives in its own file
(closes H2 — one-class-per-file rule). New code should import from the
specific module; this module is kept so existing imports keep working.
"""

# ruff: noqa: F401  — re-export facade

from kapsula.core.domain.interfaces.chunk_repository import ChunkRepository
from kapsula.core.domain.interfaces.library_card_repository import (
    LibraryCardRepository,
)
from kapsula.core.domain.interfaces.sub_document_repository import (
    SubDocumentRepository,
)
