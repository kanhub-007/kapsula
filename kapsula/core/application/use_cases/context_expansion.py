"""Context expansion for search results using LibraryCard parents."""

import json
import logging
from typing import List, Dict, Any

from kapsula.core.domain.entities.chunk import Chunk
from kapsula.core.domain.interfaces.search_data_access import SearchDataAccess

logger = logging.getLogger(__name__)


def expand_context_with_parents(
    results: List[Dict[str, Any]],
    data: SearchDataAccess,
    document_id: int,
    context_mode: str = "narrow",
) -> List[Dict[str, Any]]:
    """Expand search results with parent context from library cards.

    Pre-fetches all chunks and parent library cards in two batched queries
    instead of N+1 individual lookups per result.
    """
    if context_mode == "none" or not results:
        return results

    logger.debug(
        "Expanding context for %s results (mode=%s, doc=%s)",
        len(results), context_mode, document_id,
    )

    # ── Pre-fetch all chunks in one batch query ────────────
    chunk_specs: list[tuple[int, int | None]] = []
    for result in results:
        chunk_idx = result.get("index")
        subdoc_id = result.get("sub_document_id")
        if chunk_idx is not None:
            chunk_specs.append((chunk_idx, subdoc_id))

    chunk_map = data.get_chunks_batch(document_id, chunk_specs) if chunk_specs else {}

    # ── Resolve parent hashes from fetched chunks ──────────
    parent_hash_set: set[str] = set()
    for (c_idx, s_id), chunk in chunk_map.items():
        ph = _resolve_parent_hash(chunk, context_mode)
        if ph:
            parent_hash_set.add(ph)

    # ── Pre-fetch all parent library cards in one query ────
    parent_map = data.get_library_cards_by_doc_ids(list(parent_hash_set)) if parent_hash_set else {}

    # ── Expand results using pre-fetched data ─────────────────
    expanded_results: List[Dict[str, Any]] = []
    for result in results:
        chunk_idx = result.get("index")
        subdoc_id = result.get("sub_document_id")
        chunk = chunk_map.get((chunk_idx, subdoc_id))

        if not chunk:
            result["expanded_content"] = result["content"]
            result["context_mode"] = "none"
            expanded_results.append(result)
            continue

        parent_hash = _resolve_parent_hash(chunk, context_mode)
        if not parent_hash:
            result["expanded_content"] = result["content"]
            result["context_mode"] = "none"
            expanded_results.append(result)
            continue

        parent_card = parent_map.get(parent_hash)
        parent_text = parent_card.content if parent_card else None

        expanded = result.copy()
        if parent_text:
            expanded["expanded_content"] = parent_text
            expanded["context_mode"] = context_mode
            expanded["parent_hash"] = parent_hash
            expanded["chunk_content"] = result["content"]
        else:
            expanded["expanded_content"] = result["content"]
            expanded["context_mode"] = "none"

        expanded_results.append(expanded)

    if context_mode != "none":
        return _deduplicate(expanded_results)

    return expanded_results


def _resolve_parent_hash(chunk: Chunk, context_mode: str) -> str | None:
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
    expanded: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    deduplicated: List[Dict[str, Any]] = []
    seen_hashes: dict[str, Dict[str, Any]] = {}
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
