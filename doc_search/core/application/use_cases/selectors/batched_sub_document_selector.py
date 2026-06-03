"""Batched LLM selector for sub-document routing."""

from __future__ import annotations

import logging
from typing import Any

from doc_search.core.application.use_cases.instrumentation import log_timing
from doc_search.core.application.use_cases.selectors.id_parser import parse_ids
from doc_search.core.application.use_cases.selectors.llm_json import (
    extract_json_float,
    extract_json_int,
    extract_json_list,
    extract_json_object,
)
from doc_search.core.application.use_cases.selectors.route_decision import (
    RouteDecision,
)
from doc_search.core.domain.interfaces.chat_client import ChatClient

logger = logging.getLogger(__name__)


class BatchedSubDocumentSelector:
    """Selects sub-documents across multiple documents in one LLM call."""

    def __init__(self, chat_client: ChatClient):
        self._chat_client = chat_client

    def select(
        self, query: str, sub_documents: list[dict[str, Any]]
    ) -> dict[int, RouteDecision]:
        """Return route decisions keyed by sub-document ID."""
        if not sub_documents:
            return {}
        if len(sub_documents) == 1:
            only = sub_documents[0]
            return {
                only["id"]: RouteDecision(
                    id=only["id"], confidence=1.0, reason="Only candidate"
                )
            }

        descriptions = []
        for sd in sub_documents:
            desc = (
                f"ID {sd['id']}: {sd.get('document_filename', '?')} / "
                f"{sd['breadcrumb_key']} ({sd.get('page_count', 0)} pages)"
            )
            if titles := sd.get("page_titles", []):
                shown = titles[:5]
                if len(titles) > 5:
                    shown.append(f"... and {len(titles) - 5} more")
                desc += f"\n  Pages: {', '.join(shown)}"
            if summary := sd.get("summary"):
                desc += f"\n  Summary: {summary[:500]}"
            descriptions.append(desc)

        user_message = (
            "Given the user query and candidate document sections across multiple documents, "
            "select which sections should be searched.\n\n"
            f'Query: "{query}"\n\n'
            f"Candidate Sections:\n{chr(10).join(descriptions)}\n\n"
            "Return ONLY JSON in this format:\n"
            '{"subdocuments":[{"id":10,"confidence":0.95,"reason":"direct match"}]}\n'
            "Use confidence between 0.0 and 1.0. If unclear, include all relevant IDs."
        )

        valid_ids = [sd["id"] for sd in sub_documents]
        try:
            with log_timing(logger, "BatchedSubDocumentSelector HF chat call"):
                response = self._chat_client.send(
                    messages=[{"role": "user", "content": user_message}],
                    max_tokens=500,
                    temperature=0.1,
                )
            decisions = _parse_decisions(response, valid_ids)
            if decisions:
                logger.info(
                    "BatchedSubDocumentSelector selected %s/%s sub-docs",
                    len(decisions),
                    len(sub_documents),
                )
                return decisions
            ids = parse_ids(response, valid_ids)
            return {item_id: RouteDecision(id=item_id) for item_id in ids}
        except Exception as exc:
            logger.error("Batched sub-document selection failed: %s", exc)
            return {
                sd["id"]: RouteDecision(
                    id=sd["id"],
                    confidence=sd.get("metadata_route_confidence", 0.7),
                    reason="Metadata fallback after routing failure",
                )
                for sd in sub_documents
            }


def _parse_decisions(response: str, valid_ids: list[int]) -> dict[int, RouteDecision]:
    valid = set(valid_ids)
    payload = extract_json_object(response)
    if not payload:
        return {}

    raw_items = extract_json_list(payload, "subdocuments")
    decisions: dict[int, RouteDecision] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        item_id = extract_json_int(item, "id")
        if item_id not in valid:
            continue
        decisions[item_id] = RouteDecision(
            id=item_id,
            confidence=extract_json_float(item, "confidence", 1.0),
            reason=str(item.get("reason", "")),
        )
    return decisions
