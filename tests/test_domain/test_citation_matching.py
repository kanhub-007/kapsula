"""Tests for citation_matching domain utilities (closes H5 coverage gap).

Black-box: exercises the documented progressive-fallback contract of
``find_chunk_in_markdown`` and ``strip_inline_formatting``.
"""

from kapsula.core.domain.citation_matching import (
    find_chunk_in_markdown,
    strip_inline_formatting,
)


class TestStripInlineFormatting:
    def test_strips_bold_and_italic(self):
        assert strip_inline_formatting("**bold** and *italic*") == "bold and italic"

    def test_strips_inline_code(self):
        assert strip_inline_formatting("use `code` here") == "use code here"

    def test_strips_blockquote_prefix(self):
        assert strip_inline_formatting("> quoted text") == "quoted text"

    def test_strips_unordered_list_markers(self):
        result = strip_inline_formatting("- item one\n- item two")
        assert "item one" in result
        assert "item two" in result
        assert "- " not in result

    def test_strips_ordered_list_markers(self):
        result = strip_inline_formatting("1. first\n2. second")
        assert "first" in result
        assert "second" in result

    def test_collapses_whitespace(self):
        assert strip_inline_formatting("a\n\n\nb   c") == "a b c"


class TestFindChunkInMarkdown:
    def test_exact_match_returns_offset(self):
        md = "prefix text\n\nTARGET CHUNK here\n\nmore"
        assert find_chunk_in_markdown("TARGET CHUNK here", md) == len("prefix text\n\n")

    def test_no_match_returns_negative_one(self):
        assert find_chunk_in_markdown("does not exist", "some markdown") == -1

    def test_matches_after_inline_formatting_stripped(self):
        # The chunk text has no formatting; the markdown has bold. The
        # fallback path must still locate it.
        md = "intro\n\n**bold** plain tail\n\nend"
        pos = find_chunk_in_markdown("bold plain tail", md)
        # Found somewhere after the intro (exact offset depends on stripping;
        # the contract is just that it is found, i.e. >= 0).
        assert pos >= 0

    def test_empty_search_text_does_not_crash(self):
        # Defensive: an empty chunk search text must not raise.
        assert find_chunk_in_markdown("", "anything") in (-1, 0)
