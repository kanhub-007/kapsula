"""Domain value object for built index paths."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexPaths:
    """Paths to built FAISS and BM25 indexes."""

    faiss: str
    bm25: str
