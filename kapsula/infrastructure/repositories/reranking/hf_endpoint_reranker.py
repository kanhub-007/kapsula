"""HuggingFace Inference Endpoint reranker."""

import asyncio
from typing import Any

import aiohttp
import numpy as np
from huggingface_hub import InferenceClient

from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class HFEndpointReranker:
    """Reranker backed by a HuggingFace Inference Endpoint."""

    def __init__(self, endpoint_url: str, token: str):
        self._endpoint_url = endpoint_url
        self._client = InferenceClient(model=endpoint_url, token=token)
        self._url = f"https://router.huggingface.co/models/{endpoint_url}"
        self._headers = {"Authorization": f"Bearer {token}"}

    async def rerank(
        self, query: str, candidates: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []

        pairs = [(query, c["content"]) for c in candidates]
        scores = await self._try_batched(pairs) or await self._concurrent_fallback(
            query, candidates
        )

        for c, score in zip(candidates, scores):
            c["rerank_score"] = score

        candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        return candidates[:top_k]

    async def _try_batched(self, pairs: list) -> list[float] | None:
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self._url, json={"inputs": pairs}, headers=self._headers
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.warning(
                            f"Reranker batched returned {resp.status}: " f"{text[:500]}"
                        )
                        return None
                    data = await resp.json()
                    return [
                        (
                            float(1 / (1 + np.exp(-item[0][0])))
                            if (isinstance(item, list) and item)
                            else 0.0
                        )
                        for item in data
                    ]
        except Exception:
            logger.warning("Batched reranking failed", exc_info=True)
            return None

    async def _concurrent_fallback(
        self, query: str, candidates: list[dict[str, Any]]
    ) -> list[float]:
        logger.info("Falling back to concurrent individual reranking")
        pair_texts = [f"[CLS] {query} [SEP] {c['content']} [SEP]" for c in candidates]

        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(limit_per_host=100, limit=200)
        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout
        ) as session:
            tasks = [self._fetch_single(session, text) for text in pair_texts]
            return await asyncio.gather(*tasks)

    async def _fetch_single(self, session: aiohttp.ClientSession, text: str) -> float:
        try:
            async with session.post(
                self._url,
                json={"inputs": text},
                headers=self._headers,
                timeout=15,
            ) as resp:
                if resp.status != 200:
                    return 0.0
                data = await resp.json()
                logit = (
                    data[0][0]
                    if (isinstance(data, list) and data and isinstance(data[0], list))
                    else 0.0
                )
                return float(1 / (1 + np.exp(-logit)))
        except Exception:
            return 0.0
