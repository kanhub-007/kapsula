"""HuggingFace Inference Endpoint embedder."""

from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import List, Union, Iterator

import numpy as np
from huggingface_hub import InferenceClient

from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class HuggingFaceEmbedder:
    """Embedder backed by a HuggingFace Inference Endpoint."""

    def __init__(self, endpoint_url: str, token: str, timeout: int = 30):
        if not endpoint_url:
            raise ValueError("endpoint_url is required")
        if not token:
            raise ValueError("token is required")

        logger.info("Initializing HF Inference Client for: %s", endpoint_url)
        self._client = InferenceClient(model=endpoint_url, token=token, timeout=timeout)

    def embed(self, text: Union[str, List[str]], batch_size: int = 32) -> np.ndarray:
        """Generate embeddings. Always returns 2D."""
        texts = [text] if isinstance(text, str) else list(text)
        if not texts:
            raise ValueError("No text provided for embedding")

        started = perf_counter()
        batches = list(self._batch(texts, batch_size))

        if len(batches) > 1:
            with ThreadPoolExecutor(max_workers=min(len(batches), 8)) as pool:
                all_embeddings = list(pool.map(self._process_batch, batches))
        else:
            all_embeddings = [self._process_batch(batches[0])]

        result = (
            np.vstack(all_embeddings) if len(all_embeddings) > 1 else all_embeddings[0]
        )
        logger.info(
            "HF embedding completed in %.3fs: texts=%s single_query=%s",
            perf_counter() - started,
            len(texts),
            isinstance(text, str),
        )
        return result

    @staticmethod
    def _batch(texts: List[str], batch_size: int) -> Iterator[List[str]]:
        for start in range(0, len(texts), batch_size):
            yield texts[start : start + batch_size]

    def _process_batch(self, batch_texts: List[str]) -> np.ndarray:
        try:
            return np.array(self._client.feature_extraction(batch_texts))
        except Exception:
            logger.error(
                f"Failed to process batch of {len(batch_texts)} text(s)",
                exc_info=True,
            )
            raise
