"""Tests for json_utils — robust LLM JSON parsing.

Classical school, black-box: tests derive from the documented contract of
``_parse_json_safely`` (parse clean/fenced/prose-wrapped JSON; return {} on
garbage; never raise). No mocks.
"""

from kapsula.core.domain.json_utils import _parse_json_safely


class TestParseJsonSafely:
    """Black-box contract tests for _parse_json_safely."""

    def test_clean_json_object(self):
        """A well-formed JSON object is returned unchanged."""
        assert _parse_json_safely('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}

    def test_json_with_surrounding_whitespace(self):
        """Leading/trailing whitespace is tolerated."""
        assert _parse_json_safely('  \n  {"a": 1}  \n  ') == {"a": 1}

    def test_fenced_json_block(self):
        """Markdown ```json fenced blocks are unwrapped."""
        text = 'Here is the result:\n```json\n{"topics": [1, 2]}\n```\nDone.'
        assert _parse_json_safely(text) == {"topics": [1, 2]}

    def test_bare_fenced_json(self):
        """A code fence without the json language tag still parses."""
        assert _parse_json_safely('```\n{"k": "v"}\n```') == {"k": "v"}

    def test_prose_wrapped_json(self):
        """JSON embedded in prose is extracted by brace scanning."""
        text = 'Sure! {"plan": "go"} hope that helps'
        assert _parse_json_safely(text) == {"plan": "go"}

    def test_trailing_comma_is_tolerated(self):
        """Trailing commas (a common LLM mistake) do not break parsing."""
        assert _parse_json_safely('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}

    def test_trailing_comma_in_nested_list(self):
        """Trailing comma inside a nested list is tolerated."""
        assert _parse_json_safely('{"items": [1, 2, 3,]}') == {"items": [1, 2, 3]}

    def test_curly_quotes_normalised(self):
        """Unicode curly quotes are normalised to ASCII quotes."""
        text = "\u201ca\u201d: 1"
        assert _parse_json_safely("{" + text + "}") == {"a": 1}

    def test_empty_string_returns_empty_dict(self):
        """Empty input never raises — returns {}."""
        assert _parse_json_safely("") == {}

    def test_none_like_input(self):
        """Whitespace-only input returns {}."""
        assert _parse_json_safely("   ") == {}

    def test_garbage_returns_empty_dict(self):
        """Unparseable text returns {} rather than raising."""
        assert _parse_json_safely("totally not json at all") == {}

    def test_object_with_first_valid_prefix(self):
        """When extra text follows valid JSON, the first object is parsed."""
        text = '{"a": 1} trailing garbage {"b": 2}'
        assert _parse_json_safely(text) == {"a": 1}

    def test_nested_objects(self):
        """Nested objects are preserved."""
        result = _parse_json_safely('{"outer": {"inner": [1, {"x": 2}]}}')
        assert result == {"outer": {"inner": [1, {"x": 2}]}}

    def test_empty_object(self):
        """An empty object is a valid result."""
        assert _parse_json_safely("{}") == {}

    def test_does_not_crash_on_massive_input(self):
        """A large input string is handled without error (returns dict)."""
        big = '{"a": "' + "x" * 10000 + '"}'
        result = _parse_json_safely(big)
        assert isinstance(result, dict)
        assert len(result["a"]) == 10000
