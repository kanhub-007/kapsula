"""LLM-based intelligent search: evaluates results and formulates answers."""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from kapsula.core.application.use_cases.intelligent_search_prompts import (
    NO_ANSWER_PHRASES,
    SYSTEM_PROMPT_COMBINE,
    SYSTEM_PROMPT_EVALUATE,
    USER_MESSAGE_COMBINE,
    USER_MESSAGE_EVALUATE,
)
from kapsula.core.domain.interfaces.chat_client import ChatClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class IntelligentSearcher:
    """Evaluates search results using an LLM and generates grounded answers."""

    def __init__(self, chat_client: ChatClient):
        self._chat_client = chat_client
        logger.info("IntelligentSearcher initialized")

    # -- public API ------------------------------------------------------

    async def evaluate_and_answer_with_planning_streaming(
        self,
        query: str,
        search_function: Callable[[str], Awaitable[list[dict[str, Any]]]],
        plan: dict[str, Any] | None = None,
        max_context_length: int = 8000,
        top_k: int = 10,
    ):
        """Execute a search plan, yielding progress events."""

        if not plan:
            yield {
                "event_type": "planning",
                "data": {
                    "strategy": "single_query",
                    "total_subquestions": 1,
                    "queries": [query],
                },
            }
            search_results = await search_function(query)
            result = self.evaluate_and_answer(query, search_results, max_context_length)
            result["plan"] = None
            result["sub_answers"] = None
            yield {"event_type": "final_answer", "data": result}
            return

        yield {
            "event_type": "planning",
            "data": {
                "strategy": plan["strategy"],
                "total_subquestions": len(plan["queries"]),
                "queries": plan["queries"],
                "reasoning": plan.get("reasoning", ""),
            },
        }

        tasks = [
            self._process_sub_query(q, search_function, max_context_length, top_k)
            for q in plan["queries"]
        ]
        sub_answers: list[dict[str, Any]] = []

        for idx, task in enumerate(asyncio.as_completed(tasks)):
            yield {
                "event_type": "subquestion_start",
                "data": {
                    "subquestion_index": idx,
                    "subquestion": (
                        plan["queries"][idx] if idx < len(plan["queries"]) else ""
                    ),
                    "completed": len(sub_answers),
                    "total": len(plan["queries"]),
                },
            }
            sa = await task
            sub_answers.append(sa)
            yield {
                "event_type": "subquestion_complete",
                "data": {
                    "subquestion_index": idx,
                    "subquestion": sa["question"],
                    "answer": sa["answer"],
                    "has_answer": sa["has_answer"],
                    "num_results": sa["num_results"],
                    "completed": len(sub_answers),
                    "total": len(plan["queries"]),
                },
            }

        all_results = []
        for sa in sub_answers:
            all_results.extend(sa.get("search_results", []))

        final = await asyncio.to_thread(
            self._combine_sub_answers, query, sub_answers, max_context_length
        )
        final["search_results"] = all_results
        final["plan"] = {
            "strategy": plan["strategy"],
            "queries": plan["queries"],
            "reasoning": plan.get("reasoning", ""),
            "total_unique_results": sum(sa["num_results"] for sa in sub_answers),
            "sub_answers_count": len(sub_answers),
        }
        final["sub_answers"] = sub_answers

        yield {"event_type": "final_answer", "data": final}

    async def evaluate_and_answer_with_planning(
        self,
        query: str,
        search_function: Callable[[str], Awaitable[list[dict[str, Any]]]],
        plan: dict[str, Any] | None = None,
        max_context_length: int = 8000,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Execute a search plan and return a single result dict.

        Consumes the streaming generator (closes P2) so the planning /
        sub-query / aggregation logic has one source of truth.
        """
        final: dict[str, Any] | None = None
        async for event in self.evaluate_and_answer_with_planning_streaming(
            query=query,
            search_function=search_function,
            plan=plan,
            max_context_length=max_context_length,
            top_k=top_k,
        ):
            if event["event_type"] == "final_answer":
                final = event["data"]
        # The streaming variant always yields exactly one final_answer.
        # Raise (not ``assert``) so this is not stripped under ``python -O``.
        if final is None:
            raise RuntimeError(
                "evaluate_and_answer_with_planning_streaming did not yield "
                "a final_answer event"
            )
        return final

    def evaluate_and_answer(
        self,
        query: str,
        search_results: list[dict[str, Any]],
        max_context_length: int = 8000,
    ) -> dict[str, Any]:
        """Evaluate search results and generate a context-grounded answer."""

        if not search_results:
            return {
                "answer": "No search results were found for your query.",
                "relevant_results": [],
                "total_evaluated": 0,
                "has_answer": False,
                "search_results": [],
            }

        context_parts = []
        current_length = 0
        evaluated = 0

        for idx, result in enumerate(search_results):
            content = result.get("content", "")
            text = (
                f"[Result {idx + 1}] (Score: {result.get('score', 0):.3f})\n{content}\n"
            )
            if current_length + len(text) > max_context_length:
                break
            context_parts.append(text)
            current_length += len(text)
            evaluated += 1

        if evaluated == 0:
            return {
                "answer": "Search results are too large to process. Please refine your query.",
                "relevant_results": [],
                "total_evaluated": 0,
                "has_answer": False,
                "search_results": search_results,
            }

        context = "\n".join(context_parts)
        user_message = USER_MESSAGE_EVALUATE.format(query=query, context=context)

        try:
            raw_answer = self._chat_client.send(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_EVALUATE},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=1000,
                temperature=0.3,
            )
        except Exception as e:
            logger.exception("Intelligent search failed: %s", e)
            return {
                "answer": "An error occurred while processing your query.",
                "error": f"Intelligent search failed: {e}",
                "relevant_results": [],
                "total_evaluated": evaluated,
                "has_answer": False,
                "search_results": search_results,
            }

        # Split off the optional ``SUPPORTING_RESULTS: [...]`` trailer the
        # model is asked to emit, so the displayed answer stays clean and
        # ``relevant_results`` reflects the chunks that actually supported
        # it (closes M1: previously ALL evaluated chunks were flagged).
        answer, supporting = _split_supporting_results(raw_answer)
        has_answer = not any(p in answer.lower() for p in NO_ANSWER_PHRASES)
        if has_answer:
            relevant = _resolve_relevant_indices(supporting, evaluated)
        else:
            relevant = []

        return {
            "answer": answer,
            "relevant_results": relevant,
            "total_evaluated": evaluated,
            "has_answer": has_answer,
            "search_results": search_results,
        }

    # -- internal --------------------------------------------------------

    async def _process_sub_query(
        self,
        planned_query: str,
        search_function: Callable[[str], Awaitable[list[dict[str, Any]]]],
        max_context_length: int,
        top_k: int,
    ) -> dict[str, Any]:
        results = await search_function(planned_query)
        top = sorted(results, key=lambda x: x.get("score", 0), reverse=True)[:top_k]

        if top:
            intermediate = await asyncio.to_thread(
                self.evaluate_and_answer,
                query=planned_query,
                search_results=top,
                max_context_length=max_context_length,
            )
            return {
                "question": planned_query,
                "answer": intermediate["answer"],
                "has_answer": intermediate["has_answer"],
                "num_results": len(top),
                "search_results": intermediate.get("search_results", top),
            }

        return {
            "question": planned_query,
            "answer": "No results found for this question.",
            "has_answer": False,
            "num_results": 0,
            "search_results": [],
        }

    def _combine_sub_answers(
        self,
        original_query: str,
        sub_answers: list[dict[str, Any]],
        max_context_length: int = 8000,
    ) -> dict[str, Any]:
        if not sub_answers:
            return {
                "answer": "No information was found to answer your question.",
                "relevant_results": [],
                "total_evaluated": 0,
                "has_answer": False,
            }

        parts = []
        total = 0
        for idx, sa in enumerate(sub_answers):
            if sa["has_answer"]:
                parts.append(
                    f"[Sub-Question {idx + 1}]: {sa['question']}\n"
                    f"[Answer {idx + 1}]: {sa['answer']}\n"
                )
            total += sa["num_results"]

        if not parts:
            return {
                "answer": "I don't have enough information to answer your question based on the available documentation.",
                "relevant_results": [],
                "total_evaluated": total,
                "has_answer": False,
            }

        context = "\n".join(parts)
        if len(context) > max_context_length:
            context = context[:max_context_length] + "\n... [truncated]"

        try:
            answer = self._chat_client.send(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_COMBINE},
                    {
                        "role": "user",
                        "content": USER_MESSAGE_COMBINE.format(
                            query=original_query, context=context
                        ),
                    },
                ],
                max_tokens=1500,
                temperature=0.3,
            )
        except Exception as e:
            logger.exception("Failed to combine sub-answers: %s", e)
            return {
                "answer": None,
                "error": f"Failed to synthesize the answer: {e}",
                "relevant_results": [],
                "total_evaluated": total,
                "has_answer": False,
            }

        has_answer = not any(p in answer.lower() for p in NO_ANSWER_PHRASES)
        return {
            "answer": answer,
            "relevant_results": [],
            "total_evaluated": total,
            "has_answer": has_answer,
        }


# ---------------------------------------------------------------------------
# Module-level helpers for the SUPPORTING_RESULTS trailer (single-call
# relevance extraction — closes M1).
# ---------------------------------------------------------------------------

_SUPPORTING_RE = re.compile(r"SUPPORTING_RESULTS\s*:\s*\[([^\]]*)\]", re.IGNORECASE)


def _split_supporting_results(raw_answer: str) -> tuple[str, list[int] | None]:
    """Split a model answer into (clean_answer, supporting_indices|None).

    The model is asked to append ``SUPPORTING_RESULTS: [1, 3, 5]``. We parse
    it defensively: any malformed trailer is ignored and the whole text is
    returned as the answer. Returns ``None`` for the indices when no trailer
    is present so the caller can apply its fallback policy.
    """
    match = _SUPPORTING_RE.search(raw_answer)
    if not match:
        return raw_answer.strip(), None
    inner = match.group(1)
    indices: list[int] = []
    for token in inner.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            indices.append(int(token))
        except ValueError:
            continue
    # Remove the trailer so the user-facing answer stays clean.
    clean = raw_answer[: match.start()].rstrip()
    tail = raw_answer[match.end() :].strip()
    if tail:
        clean = f"{clean}\n{tail}" if clean else tail
    return clean, indices


def _resolve_relevant_indices(
    supporting: list[int] | None, evaluated: int
) -> list[int]:
    """Normalise 1-based supporting indices to validated 0-based indices.

    Falls back to ``list(range(evaluated))`` only when the model emitted no
    trailer at all (preserves the previous behaviour as a last resort).
    Out-of-range / non-positive values are dropped.
    """
    if supporting is None:
        return list(range(evaluated))
    resolved: list[int] = []
    seen: set[int] = set()
    for one_based in supporting:
        idx = one_based - 1
        if 0 <= idx < evaluated and idx not in seen:
            seen.add(idx)
            resolved.append(idx)
    return resolved
