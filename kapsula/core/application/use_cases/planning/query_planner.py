"""LLM-based query planning for intelligent search."""

import logging
from typing import Any

from kapsula.core.domain.interfaces.chat_client import ChatClient
from kapsula.core.domain.json_utils import parse_json_safely

from .query_planning_prompts import SYSTEM_PROMPT_DOCUMENT, USER_MESSAGE_DOCUMENT

logger = logging.getLogger(__name__)


class QueryPlanner:
    """Creates intelligent search plans based on user questions and documentation structure."""

    def __init__(self, chat_client: ChatClient):
        self._chat_client = chat_client

    def plan_document_search(
        self,
        query: str,
        document_library_card: dict[str, Any] | None = None,
        document_structure: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not document_structure:
            return {
                "strategy": "single_query",
                "queries": [query],
                "reasoning": "No document structure available",
            }

        context = self._build_context(document_library_card, document_structure)

        try:
            response = self._chat_client.send(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_DOCUMENT},
                    {
                        "role": "user",
                        "content": USER_MESSAGE_DOCUMENT.format(
                            query=query, context=context
                        ),
                    },
                ],
                max_tokens=500,
                temperature=0.3,
            )
            plan = parse_json_safely(response)
            return self._validate(plan, query)
        except Exception as e:
            logger.exception(f"Query planning failed: {e}")
            return {
                "strategy": "single_query",
                "queries": [query],
                "reasoning": "Planning error — using original query",
            }

    @staticmethod
    def _build_context(card: dict | None, structure: list) -> str:
        parts = []
        if card:
            parts.append(f"Document: {card.get('title', 'Unknown')}")

        if structure:
            parts.append("Document Structure (Hierarchical Headings):")
            for struct in structure[:15]:
                name = struct.get("subdocument_name", "Unknown")
                sections = struct.get("sections", [])
                parts.append(f"\n## {name}")
                for level, key in [
                    ("H1", "level_3"),
                    ("H2", "level_2"),
                    ("H3", "level_1"),
                ]:
                    titles = [s["title"] for s in sections if s["level"] == key][:8]
                    if titles:
                        parts.append(f"  {level}: {', '.join(titles)}")

            if len(structure) > 15:
                parts.append(f"\n... and {len(structure) - 15} more sections")

        return "\n".join(parts) if parts else "No document context available"

    @staticmethod
    def _validate(plan: dict, fallback_query: str) -> dict:
        if plan.get("strategy") not in ("single_query", "multi_query"):
            plan["strategy"] = "single_query"
        if not isinstance(plan.get("queries"), list) or not plan["queries"]:
            plan["queries"] = [fallback_query]
        plan["queries"] = plan["queries"][:5]
        return plan
