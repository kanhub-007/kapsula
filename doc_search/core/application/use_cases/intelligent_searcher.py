"""LLM-based intelligent search: evaluates results and formulates answers."""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Callable, Awaitable
from doc_search.core.domain.interfaces.chat_client import ChatClient

from doc_search.core.application.use_cases.intelligent_search_prompts import (
    SYSTEM_PROMPT_EVALUATE,
    USER_MESSAGE_EVALUATE,
    SYSTEM_PROMPT_COMBINE,
    USER_MESSAGE_COMBINE,
    _NO_ANSWER_PHRASES,
)

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
        search_function: Callable[[str], Awaitable[List[Dict[str, Any]]]],
        plan: Optional[Dict[str, Any]] = None,
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
        sub_answers: List[Dict[str, Any]] = []

        for idx, task in enumerate(asyncio.as_completed(tasks)):
            yield {
                "event_type": "subquestion_start",
                "data": {
                    "subquestion_index": idx,
                    "subquestion": plan["queries"][idx] if idx < len(plan["queries"]) else "",
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
        search_function: Callable[[str], Awaitable[List[Dict[str, Any]]]],
        plan: Optional[Dict[str, Any]] = None,
        max_context_length: int = 8000,
        top_k: int = 10,
    ) -> Dict[str, Any]:
        """Execute a search plan and return a single result dict."""

        if not plan:
            search_results = await search_function(query)
            result = self.evaluate_and_answer(query, search_results, max_context_length)
            result["plan"] = None
            result["sub_answers"] = None
            return result

        tasks = [
            self._process_sub_query(q, search_function, max_context_length, top_k)
            for q in plan["queries"]
        ]
        sub_answers = await asyncio.gather(*tasks)

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
        return final

    def evaluate_and_answer(
        self,
        query: str,
        search_results: List[Dict[str, Any]],
        max_context_length: int = 8000,
    ) -> Dict[str, Any]:
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
            text = f"[Result {idx + 1}] (Score: {result.get('score', 0):.3f})\n{content}\n"
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
            answer = self._chat_client.send(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_EVALUATE},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=1000,
                temperature=0.3,
            )
        except Exception as e:
            logger.error(f"Intelligent search failed: {e}", exc_info=True)
            return {
                "answer": f"An error occurred while processing your query: {e}",
                "relevant_results": [],
                "total_evaluated": evaluated,
                "has_answer": False,
                "search_results": search_results,
            }

        has_answer = not any(p in answer.lower() for p in _NO_ANSWER_PHRASES)
        relevant = list(range(evaluated)) if has_answer else []

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
        search_function: Callable[[str], Awaitable[List[Dict[str, Any]]]],
        max_context_length: int,
        top_k: int,
    ) -> Dict[str, Any]:
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
        sub_answers: List[Dict[str, Any]],
        max_context_length: int = 8000,
    ) -> Dict[str, Any]:
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
                    {"role": "user", "content": USER_MESSAGE_COMBINE.format(query=original_query, context=context)},
                ],
                max_tokens=1500,
                temperature=0.3,
            )
        except Exception as e:
            logger.error(f"Failed to combine sub-answers: {e}", exc_info=True)
            return {
                "answer": f"An error occurred while synthesizing the answer: {e}",
                "relevant_results": [],
                "total_evaluated": total,
                "has_answer": False,
            }

        has_answer = not any(p in answer.lower() for p in _NO_ANSWER_PHRASES)
        return {
            "answer": answer,
            "relevant_results": [],
            "total_evaluated": total,
            "has_answer": has_answer,
        }
