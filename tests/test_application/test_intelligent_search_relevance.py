"""Tests for the SUPPORTING_RESULTS relevance extraction (closes M1/H5).

Black-box: the helper must split the machine-readable trailer from the
user-facing answer, parse indices defensively, and fall back to the legacy
"all evaluated" policy only when no trailer is present.
"""

from kapsula.core.application.use_cases.intelligent_searcher import (
    _resolve_relevant_indices,
    _split_supporting_results,
)


class TestSplitSupportingResults:
    def test_no_trailer_returns_whole_answer_and_none(self):
        answer, supporting = _split_supporting_results("Just a plain answer.")
        assert answer == "Just a plain answer."
        assert supporting is None

    def test_extracts_one_based_indices(self):
        raw = "The answer.\nSUPPORTING_RESULTS: [1, 3, 5]"
        answer, supporting = _split_supporting_results(raw)
        assert "SUPPORTING_RESULTS" not in answer
        assert supporting == [1, 3, 5]

    def test_case_insensitive_and_whitespace_tolerant(self):
        raw = "Answer.\nsupporting_results: [2,4]"
        answer, supporting = _split_supporting_results(raw)
        assert supporting == [2, 4]

    def test_malformed_tokens_are_dropped_not_raised(self):
        raw = "Answer.\nSUPPORTING_RESULTS: [1, oops, 3, ]"
        _, supporting = _split_supporting_results(raw)
        assert supporting == [1, 3]

    def test_trailer_text_after_bracket_is_preserved(self):
        raw = "Answer.\nSUPPORTING_RESULTS: [1]\ntrailing note"
        answer, _ = _split_supporting_results(raw)
        assert answer.endswith("trailing note")


class TestResolveRelevantIndices:
    def test_none_falls_back_to_all_evaluated(self):
        # Preserves the previous behaviour as a last resort.
        assert _resolve_relevant_indices(None, 4) == [0, 1, 2, 3]

    def test_converts_one_based_to_zero_based(self):
        assert _resolve_relevant_indices([1, 3], 5) == [0, 2]

    def test_drops_out_of_range(self):
        assert _resolve_relevant_indices([0, 1, 9], 3) == [0]

    def test_deduplicates(self):
        assert _resolve_relevant_indices([1, 1, 2], 5) == [0, 1]

    def test_empty_list_returns_empty(self):
        assert _resolve_relevant_indices([], 5) == []
