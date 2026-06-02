"""LLM-based sub-document selector."""

import logging
from typing import List, Dict, Any

from doc_search.core.application.use_cases.instrumentation import log_timing
from doc_search.core.domain.interfaces.chat_client import ChatClient
from .id_parser import parse_ids

logger = logging.getLogger(__name__)


class SubDocumentSelector:
    """Selects relevant sub-document indexes for a query using LLM."""

    def __init__(self, chat_client: ChatClient):
        self._chat_client = chat_client

    def select(self, query: str, sub_documents: List[Dict[str, Any]]) -> List[int]:
        if not sub_documents:
            return []

        descriptions = []
        for sd in sub_documents:
            desc = (
                f"ID {sd['id']}: {sd['breadcrumb_key']} "
                f"({sd.get('page_count', 0)} pages)"
            )
            if titles := sd.get("page_titles", []):
                shown = titles[:5]
                if len(titles) > 5:
                    shown.append(f"... and {len(titles) - 5} more")
                desc += f"\n  Pages: {', '.join(shown)}"
            descriptions.append(desc)

        user_message = (
            f"Given the user query and available document sections, select which sections to search.\n\n"
            f'Query: "{query}"\n\n'
            f"Available Sections:\n{chr(10).join(descriptions)}\n\n"
            f'Return ONLY a comma-separated list of section IDs to search (e.g., "1,3,5").\n'
            f"If the query is general or could match multiple sections, return relevant section IDs.\n"
            f"If unclear, return ALL section IDs.\n"
            f"Do not include any explanation, only the IDs."
        )

        try:
            with log_timing(logger, "SubDocumentSelector HF chat call"):
                response = self._chat_client.send(
                    messages=[{"role": "user", "content": user_message}],
                    max_tokens=50,
                    temperature=0.1,
                )
            valid = [sd["id"] for sd in sub_documents]
            selected = parse_ids(response, valid)
            logger.info(
                "SubDocumentSelector selected %s/%s sub-docs",
                len(selected),
                len(sub_documents),
            )
            return selected
        except Exception as e:
            logger.error(f"Selection failed: {e}")
            return [sd["id"] for sd in sub_documents]
