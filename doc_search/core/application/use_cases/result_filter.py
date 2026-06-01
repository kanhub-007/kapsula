"""Search result node-type filtering (application-level)."""

from typing import List, Dict, Any

logger = __import__("logging").getLogger(__name__)


def filter_by_node_type(
    results: List[Dict[str, Any]],
    node_types: List[str] | None = None,
) -> List[Dict[str, Any]]:
    if not node_types:
        return results

    filtered = []
    for result in results:
        try:
            metadata = result.get("metadata", {})
            if isinstance(metadata, str):
                import json
                metadata = json.loads(metadata)
            if metadata.get("node_type", "text") in node_types:
                filtered.append(result)
        except Exception:
            filtered.append(result)

    logger.debug(f"Node-type filter: {len(results)} -> {len(filtered)}")
    return filtered
