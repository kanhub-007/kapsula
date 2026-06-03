"""Context expansion for search results using LibraryCard parents."""

import json
import logging
from typing import List, Dict, Any

from kapsula.core.domain.interfaces.search_data_access import SearchDataAccess
from kapsula.core.domain.entities.chunk import Chunk

logger = logging.getLogger(__name__)


def expand_context_with_parents(
    results: List[Dict[str, Any]],
    data: SearchDataAccess,
    document_id: int,
    context_mode: str = "narrow",
) -> List[Dict[str, Any]]:
    if context_mode == "none" or not results:
        return results

    logger.debug(
        f"Expanding context for {len(results)} results "
        f"(mode={context_mode}, doc={document_id})"
    )

    expanded_results = [
        _expand_single(r, data, document_id, context_mode) for r in results
    ]

    if context_mode != "none":
        return _deduplicate(expanded_results)

    return expanded_results


def _expand_single(
    result: Dict[str, Any],
    data: SearchDataAccess,
    document_id: int,
    context_mode: str,
) -> Dict[str, Any]:
    chunk_index = result.get("index")
    result_subdoc_id = result.get("sub_document_id")

    chunk = data.get_chunk(document_id, chunk_index, result_subdoc_id)
    if not chunk:
        logger.debug(f"Chunk not found: doc={document_id}, idx={chunk_index}")
        result["expanded_content"] = result["content"]
        result["context_mode"] = "none"
        return result

    parent_hash = _resolve_parent_hash(chunk, context_mode)
    if not parent_hash:
        result["expanded_content"] = result["content"]
        result["context_mode"] = "none"
        return result

    parent_content = data.get_library_card_by_doc_id(parent_hash, chunk.sub_document_id)
    parent_text = parent_content.content if parent_content else None

    expanded = result.copy()
    if parent_text:
        expanded["expanded_content"] = parent_text
        expanded["context_mode"] = context_mode
        expanded["parent_hash"] = parent_hash
        expanded["chunk_content"] = result["content"]
    else:
        expanded["expanded_content"] = result["content"]
        expanded["context_mode"] = "none"

    return expanded


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
