"""Internal search utilities shared by MultiIndexSearcher."""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


def _select(selector, query: str, metadata: list[dict]) -> list[dict]:
    ids = selector.select(query, metadata)
    return [m for m in metadata if m["id"] in ids]


def _document_concurrency() -> int:
    try:
        return max(1, int(os.getenv("KAPSULA_DOCUMENT_CONCURRENCY", "4")))
    except ValueError:
        logger.warning("Invalid KAPSULA_DOCUMENT_CONCURRENCY; falling back to 4")
        return 4


async def _gather(tasks: list) -> list:
    nested = await asyncio.gather(*tasks, return_exceptions=True)
    results = []
    for item in nested:
        if isinstance(item, list):
            results.extend(item)
        elif isinstance(item, Exception):
            logger.error(f"Search exception: {item}")
    return results
