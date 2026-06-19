"""Context expansion for search results using LibraryCard parents."""

import json
import logging
from typing import Any

from kapsula.core.domain.interfaces.search_data_access import SearchDataAccess
from kapsula.core.domain.read_models.chunk_read import ChunkRead

logger = logging.getLogger(__name__)


def expand_context_with_parents(
    results: list[dict[str, Any]],
    data: SearchDataAccess,
    document_id: int,
    context_mode: str = "narrow",
) -> list[dict[str, Any]]:
    """Expand search results with parent context from library cards.

    Pre-fetches all chunks and parent library cards in two batched queries
    instead of N+1 individual lookups per result.
    """
    if context_mode == "none" or not results:
        return results

    logger.debug(
        "Expanding context for %s results (mode=%s, doc=%s)",
        len(results),
        context_mode,
        document_id,
    )

    chunk_specs = _build_chunk_specs(results)
    chunk_map, parent_map = _fetch_context_data(
        data, document_id, chunk_specs, context_mode
    )
    expanded = _expand_results(results, chunk_map, parent_map, context_mode)

    if context_mode != "none":
        return _deduplicate(expanded)
    return expanded


# ── internal phases ────────────────────────────────────────


def _build_chunk_specs(
    results: list[dict[str, Any]],
) -> list[tuple[int, int | None]]:
    """Collect (chunk_index, sub_document_id) pairs from search results."""
    specs: list[tuple[int, int | None]] = []
    for result in results:
        chunk_idx = result.get("index")
        subdoc_id = result.get("sub_document_id")
        if chunk_idx is not None:
            specs.append((chunk_idx, subdoc_id))
    return specs


def _fetch_context_data(
    data: SearchDataAccess,
    document_id: int,
    chunk_specs: list[tuple[int, int | None]],
    context_mode: str,
) -> tuple[dict, dict]:
    """Batch-fetch chunks and parent library cards.

    Returns (chunk_map, parent_map) where chunk_map keys are
    (chunk_index, sub_doc_id) and parent_map keys are doc_id hashes.
    """
    chunk_map = data.get_chunks_batch(document_id, chunk_specs) if chunk_specs else {}

    parent_hashes: set[str] = set()
    for chunk in chunk_map.values():
        ph = _resolve_parent_hash(chunk, context_mode)
        if ph:
            parent_hashes.add(ph)

    parent_map = (
        data.get_library_cards_by_doc_ids(list(parent_hashes)) if parent_hashes else {}
    )
    return chunk_map, parent_map


def _expand_results(
    results: list[dict[str, Any]],
    chunk_map: dict,
    parent_map: dict,
    context_mode: str,
) -> list[dict[str, Any]]:
    """Expand each result with parent context from pre-fetched data."""
    expanded: list[dict[str, Any]] = []
    for result in results:
        chunk = chunk_map.get((result.get("index"), result.get("sub_document_id")))

        if not chunk:
            result["expanded_content"] = result["content"]
            result["context_mode"] = "none"
            expanded.append(result)
            continue

        parent_hash = _resolve_parent_hash(chunk, context_mode)
        if not parent_hash:
            result["expanded_content"] = result["content"]
            result["context_mode"] = "none"
            expanded.append(result)
            continue

        parent_card = parent_map.get(parent_hash)
        parent_text = parent_card.content if parent_card else None

        exp = result.copy()
        if parent_text:
            exp["expanded_content"] = parent_text
            exp["context_mode"] = context_mode
            exp["parent_hash"] = parent_hash
            exp["chunk_content"] = result["content"]
        else:
            exp["expanded_content"] = result["content"]
            exp["context_mode"] = "none"

        expanded.append(exp)
    return expanded


def _resolve_parent_hash(chunk: ChunkRead, context_mode: str) -> str | None:
    """Extract parent hash from chunk metadata based on context mode."""
    metadata = {}
    if chunk.chunk_metadata:
        try:
            metadata = json.loads(chunk.chunk_metadata)
        except json.JSONDecodeError:
            pass

    parents = metadata.get("parents", {})
    if context_mode == "narrow":
        return parents.get("immediate")
    if context_mode == "deep":
        return parents.get("chapter")
    return None


def _deduplicate(
    expanded: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate expanded results by parent hash, aggregating scores."""
    deduplicated: list[dict[str, Any]] = []
    seen_hashes: dict[str, dict[str, Any]] = {}
    seen_indices: set[int] = set()

    for result in expanded:
        parent_hash = result.get("parent_hash")
        chunk_index = result.get("index")

        if parent_hash:
            if parent_hash not in seen_hashes:
                result["contributing_chunks"] = [chunk_index]
                result["contributing_scores"] = [result.get("score", 0)]
                seen_hashes[parent_hash] = result
                deduplicated.append(result)
            else:
                first = seen_hashes[parent_hash]
                first["contributing_chunks"].append(chunk_index)
                first["contributing_scores"].append(result.get("score", 0))
                first["score"] = max(first["contributing_scores"])
        elif chunk_index not in seen_indices:
            seen_indices.add(chunk_index)
            result["contributing_chunks"] = [chunk_index]
            result["contributing_scores"] = [result.get("score", 0)]
            deduplicated.append(result)

    return deduplicated
