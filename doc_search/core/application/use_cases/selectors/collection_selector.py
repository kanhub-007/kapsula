"""LLM-based collection selector."""

import logging
from typing import List, Dict, Any

from doc_search.core.application.use_cases.instrumentation import log_timing
from doc_search.core.domain.interfaces.chat_client import ChatClient
from .id_parser import parse_ids

logger = logging.getLogger(__name__)


class CollectionSelector:
    """Selects relevant collections for a query using LLM and library cards."""

    def __init__(self, chat_client: ChatClient):
        self._chat_client = chat_client

    def select(self, query: str, collections: List[Dict[str, Any]]) -> List[int]:
        if not collections:
            return []
        if len(collections) == 1:
            return [collections[0]["id"]]

        descriptions = []
        for coll in collections:
            desc = (
                f"ID {coll['id']}: {coll['name']} "
                f"({coll.get('document_count', 0)} documents)"
            )
            if summary := coll.get("library_card_summary"):
                desc += f"\n  Summary: {summary}"
            if docs := coll.get("document_list", []):
                shown = docs[:3]
                if len(docs) > 3:
                    shown.append(f"... and {len(docs) - 3} more")
                desc += f"\n  Documents: {', '.join(shown)}"
            descriptions.append(desc)

        user_message = (
            f"Given the user query and available collections, select which collections to search.\n\n"
            f'Query: "{query}"\n\n'
            f"Available Collections:\n{chr(10).join(descriptions)}\n\n"
            f'Return ONLY a comma-separated list of collection IDs to search (e.g., "1,3,5").\n'
            f"If the query is general or could match multiple collections, return relevant collection IDs.\n"
            f"If unclear, return ALL collection IDs.\n"
            f"Do not include any explanation, only the IDs."
        )

        try:
            with log_timing(logger, "CollectionSelector HF chat call"):
                response = self._chat_client.send(
                    messages=[{"role": "user", "content": user_message}],
                    max_tokens=50,
                    temperature=0.1,
                )
            valid = [c["id"] for c in collections]
            selected = parse_ids(response, valid)
            logger.info(
                "CollectionSelector selected %s/%s collections",
                len(selected),
                len(collections),
            )
            return selected
        except Exception as e:
            logger.error(f"Collection selection failed: {e}")
            return [c["id"] for c in collections]
