"""Tests for text_processing domain utilities (closes H5 coverage gap).

Black-box: exercises the documented contract of each public function —
node-type parsing, simple stemming (with a bounded LRU cache), tokenization,
and the meaningful-chunk heuristic.
"""

from kapsula.core.domain import text_processing as tp


class TestParseNodeTypeFilter:
    def test_none_returns_none(self):
        assert tp.parse_node_type_filter(None) is None

    def test_empty_returns_none(self):
        assert tp.parse_node_type_filter("") is None
        assert tp.parse_node_type_filter("   ") is None

    def test_single_value(self):
        assert tp.parse_node_type_filter("code") == ["code"]

    def test_comma_separated_strips_whitespace_and_empties(self):
        assert tp.parse_node_type_filter(" table , , code ,") == ["table", "code"]


class TestSimpleStem:
    def test_short_word_lowercased_unchanged(self):
        assert tp.simple_stem("Cat") == "cat"
        assert tp.simple_stem("the") == "the"

    def test_plural_s(self):
        assert tp.simple_stem("dogs") == "dog"

    def test_ies_to_y(self):
        assert tp.simple_stem("libraries") == "library"

    def test_es_stripped(self):
        assert tp.simple_stem("boxes") == "box"

    def test_ed_stripped(self):
        assert tp.simple_stem("played") == "play"

    def test_ing_stripped(self):
        assert tp.simple_stem("running") == "runn"

    def test_case_insensitive_cache_key(self):
        # Same word in different cases must stem identically (cache is
        # keyed on the lower-cased form).
        assert tp.simple_stem("Dogs") == tp.simple_stem("dogs")


class TestTokenize:
    def test_lowercases_and_stems(self):
        tokens = tp.tokenize("The Dogs are running")
        assert "dog" in tokens
        assert "the" in tokens

    def test_non_word_chars_split(self):
        assert tp.tokenize("a-b.c") == ["a", "b", "c"]


class TestIsMeaningfulChunk:
    def test_short_content_is_not_meaningful(self):
        assert tp.is_meaningful_chunk("too short") is False

    def test_under_min_words_is_not_meaningful(self):
        # 50+ chars but only one 2+ char word
        long_one_word = "x" * 60
        assert tp.is_meaningful_chunk(long_one_word) is False

    def test_normal_sentence_is_meaningful(self):
        text = "This is a normal sentence with enough words to be meaningful here."
        assert tp.is_meaningful_chunk(text) is True

    def test_custom_min_words(self):
        text = "one two three four five six seven eight nine ten characters"
        assert tp.is_meaningful_chunk(text, min_words=20) is False


def test_stem_cache_is_bounded_and_clearable():
    # Exercise the cache then clear it — verifies the clear hook exists and
    # the LRU cache metadata is populated (closes H4 regression guard).
    tp.simple_stem("cached_word_xyz")
    info_before = tp._stem_inner.cache_info()
    assert info_before.currsize >= 1
    tp.clear_stem_cache()
    info_after = tp._stem_inner.cache_info()
    assert info_after.currsize == 0
