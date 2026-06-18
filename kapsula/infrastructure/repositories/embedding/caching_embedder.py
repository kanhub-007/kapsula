"""Embedder decorator that caches repeated single-query embeddings."""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import List, Union

import numpy as np

from kapsula.core.domain.interfaces.embedder import Embedder
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class CachingEmbedder:
    """Decorator for ``Embedder`` that caches single-string query embeddings.

    Batch calls are deliberately not cached because ingestion can pass large,
    unique batches where caching would waste memory and risk stale assumptions.
    """

    def __init__(
        self,
        inner: Embedder,
        namespace: str = "default",
        max_entries: int = 256,
    ):
        self._inner = inner
        self._namespace = namespace
        self._max_entries = max(1, max_entries)
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = Lock()

    def embed(self, text: Union[str, List[str]], batch_size: int = 32) -> np.ndarray:
        """Generate embeddings, caching only single-string requests."""
        if not isinstance(text, str):
            return self._inner.embed(text, batch_size=batch_size)

        cached = self._get(text)
        if cached is not None:
            logger.debug("Embedding cache hit for single query")
            return cached

        result = self._inner.embed(text, batch_size=batch_size)
        self._set(text, result)
        return result

    def clear_cache(self) -> None:
        """Clear cached embeddings (used by tests and MCP cache reset)."""
        with self._lock:
            self._cache.clear()

    def _key(self, query: str) -> str:
        normalized = " ".join(query.strip().lower().split())
        return f"{self._namespace}\0{normalized}"

    def _get(self, query: str) -> np.ndarray | None:
        key = self._key(query)
        with self._lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            self._cache.move_to_end(key)
            return cached

    def _set(self, query: str, embedding: np.ndarray) -> None:
        key = self._key(query)
        with self._lock:
            self._cache[key] = embedding
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)
