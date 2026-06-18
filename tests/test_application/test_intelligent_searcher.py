"""Tests for IntelligentSearcher — Classical school, fake ChatClient.

Black-box: exercises the documented contract — evaluate search results,
generate grounded answers, decompose plans into sub-queries, synthesise
sub-answers. Asserts on the returned result, never on chat_client calls.
"""

import asyncio

from kapsula.core.application.use_cases.intelligent_searcher import (
    IntelligentSearcher,
)
from kapsula.core.domain.interfaces.chat_client import ChatClient


class FakeChatClient(ChatClient):
    """Returns canned responses from a FIFO queue."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.sent: list[list[dict]] = []

    def send(self, messages, max_tokens=500, temperature=0.3) -> str:
        self.sent.append(messages)
        if not self._responses:
            return "{}"
        return self._responses.pop(0)


def _result(score: float, content: str, idx: int = 0) -> dict:
    return {"index": idx, "score": score, "content": content}


class TestEvaluateAndAnswer:
    def test_empty_search_results_returns_no_results_answer(self):
        client = FakeChatClient([])
        searcher = IntelligentSearcher(client)

        result = searcher.evaluate_and_answer(
            "q", search_results=[], max_context_length=1000
        )

        assert result["has_answer"] is False
        assert "No search results" in result["answer"]
        assert result["total_evaluated"] == 0
        # Client was never called.
        assert client.sent == []

    def test_grounded_answer_marks_has_answer_true(self):
        client = FakeChatClient(["The answer is 42."])
        searcher = IntelligentSearcher(client)

        results = [_result(0.9, "The answer is 42 according to the docs.", 0)]
        result = searcher.evaluate_and_answer("q", results, max_context_length=1000)

        assert result["has_answer"] is True
        assert result["answer"] == "The answer is 42."
        assert result["total_evaluated"] == 1
        assert result["relevant_results"] == [0]

    def test_no_answer_phrase_flips_has_answer_false(self):
        client = FakeChatClient(["I don't have enough information to answer."])
        searcher = IntelligentSearcher(client)

        results = [_result(0.3, "unrelated content", 0)]
        result = searcher.evaluate_and_answer("q", results, max_context_length=1000)

        assert result["has_answer"] is False
        assert result["relevant_results"] == []

    def test_context_length_truncates_evaluated_results(self):
        # Each result contributes ~50 chars of framing + 1000 chars content.
        big = "x" * 1000
        results = [_result(0.9, big, i) for i in range(20)]
        client = FakeChatClient(["answer"])
        searcher = IntelligentSearcher(client)

        result = searcher.evaluate_and_answer("q", results, max_context_length=2000)

        # Only a few results fit before the budget is exhausted.
        assert 0 < result["total_evaluated"] < 20

    def test_chat_failure_returns_error_without_raising(self):
        class _ExplodingClient(ChatClient):
            def send(self, messages, max_tokens=500, temperature=0.3) -> str:
                raise RuntimeError("LLM down")

        searcher = IntelligentSearcher(_ExplodingClient())
        results = [_result(0.9, "content", 0)]

        result = searcher.evaluate_and_answer("q", results, max_context_length=1000)

        assert result["has_answer"] is False
        assert "error" in result


class TestEvaluateAndAnswerWithPlanning:
    def test_no_plan_runs_single_query(self):
        client = FakeChatClient(["single answer"])
        searcher = IntelligentSearcher(client)

        async def search_fn(q: str):
            return [_result(0.9, "evidence")]

        result = asyncio.run(
            searcher.evaluate_and_answer_with_planning(
                "q", search_fn, plan=None, max_context_length=1000
            )
        )

        assert result["plan"] is None
        assert result["sub_answers"] is None
        assert result["has_answer"] is True

    def test_plan_with_two_subqueries_aggregates(self):
        # Two evaluate responses (one per sub-query) + one combine response.
        client = FakeChatClient(
            [
                "sub-answer one",
                "sub-answer two",
                "Combined final answer.",
            ]
        )
        searcher = IntelligentSearcher(client)
        plan = {
            "strategy": "multi_query",
            "queries": ["sub1", "sub2"],
            "reasoning": "decompose",
        }
        calls: list[str] = []

        async def search_fn(q: str):
            calls.append(q)
            return [_result(0.8, f"evidence for {q}")]

        result = asyncio.run(
            searcher.evaluate_and_answer_with_planning(
                "original", search_fn, plan=plan, max_context_length=2000
            )
        )

        assert set(calls) == {"sub1", "sub2"}
        assert result["plan"]["strategy"] == "multi_query"
        assert result["plan"]["sub_answers_count"] == 2
        assert len(result["sub_answers"]) == 2
        assert result["answer"] == "Combined final answer."

    def test_combine_failure_returns_has_answer_false(self):
        class _CombineExploder(ChatClient):
            def __init__(self):
                self.n = 0

            def send(self, messages, max_tokens=500, temperature=0.3) -> str:
                self.n += 1
                # First two calls = sub-query evaluations; third = combine.
                if self.n <= 2:
                    return "sub-answer"
                raise RuntimeError("combine failed")

        searcher = IntelligentSearcher(_CombineExploder())
        plan = {"strategy": "multi_query", "queries": ["a", "b"], "reasoning": ""}

        async def search_fn(q: str):
            return [_result(0.8, "evidence")]

        result = asyncio.run(
            searcher.evaluate_and_answer_with_planning(
                "q", search_fn, plan=plan, max_context_length=2000
            )
        )

        assert result["has_answer"] is False
        assert "error" in result
