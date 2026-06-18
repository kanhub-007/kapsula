"""FAISS and BM25 index loaders."""

import os
import pickle
from typing import Any

import faiss

from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class _Bm25Unpickler(pickle.Unpickler):
    """Restricted unpickler for BM25 index files.

    ``pickle.load`` executes arbitrary code, so a tampered ``.bm25`` /
    ``.pkl`` file is an RCE vector. BM25 indexes written by kapsula only
    contain a ``BM25Plus`` (or legacy ``BM25Okapi``) instance, a list of
    texts, and primitive/numpy containers. This allowlist rejects
    anything else.

    Extend ``_ALLOWED_MODULES`` if new safe globals are intentionally
    introduced — never broaden to ``*``.
    """

    _ALLOWED_MODULES = frozenset(
        {
            "rank_bm25",
            "numpy",
            "numpy.core",
            "numpy.core.numeric",
            "collections",
            "builtins",
        }
    )

    def find_class(self, module: str, name: str) -> Any:
        if module not in self._ALLOWED_MODULES:
            raise pickle.UnpicklingError(
                f"Refusing to unpickle disallowed global {module}.{name} "
                f"(BM25 index loader allowlist)"
            )
        return super().find_class(module, name)


def load_faiss_index(index_path: str) -> faiss.Index:
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"FAISS index not found: {index_path}")
    index = faiss.read_index(index_path)
    logger.debug(f"Loaded FAISS index with {index.ntotal} vectors")
    return index


def load_bm25_index(index_path: str) -> tuple[Any, list[str]]:
    """Load a BM25 index written by :mod:`document_index_builder`.

    Uses :class:`_Bm25Unpickler` so a tampered file cannot execute
    arbitrary code. The expected payload is ``{"bm25": BM25Plus,
    "texts": list[str]}``.
    """
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"BM25 index not found: {index_path}")
    with open(index_path, "rb") as f:
        data = _Bm25Unpickler(f).load()
    logger.debug(f"Loaded BM25 index with {len(data['texts'])} documents")
    return data["bm25"], data["texts"]
