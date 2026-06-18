"""Text embedding protocol."""

from typing import Protocol

import numpy as np


class Embedder(Protocol):
    """Interface for text embedding backends."""

    def embed(self, text: str | list[str], batch_size: int = 32) -> np.ndarray:
        """Return a 2D array: ``(1, dim)`` for single text, ``(n, dim)`` for batch."""
        ...
