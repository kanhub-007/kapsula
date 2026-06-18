"""Internal search utilities shared by MultiIndexSearcher."""

import asyncio
import logging

logger = logging.getLogger(__name__)

#: Default per-collection document-search concurrency when none is injected.
DEFAULT_DOCUMENT_CONCURRENCY = 4


def _select(selector, query: str, metadata: list[dict]) -> list[dict]:
    ids = selector.select(query, metadata)
    return [m for m in metadata if m["id"] in ids]


async def _gather(tasks: list) -> list:
    """Flatten gather() results; log and drop exceptions (never raise).

    Each sub-task already catches its own errors and returns ``[]``; this
    guard is defence-in-depth for unexpected failures.
    """
    nested = await asyncio.gather(*tasks, return_exceptions=True)
    results: list = []
    for item in nested:
        if isinstance(item, list):
            results.extend(item)
        elif isinstance(item, Exception):
            logger.error("Unhandled search task exception: %s", item, exc_info=item)
    return results
