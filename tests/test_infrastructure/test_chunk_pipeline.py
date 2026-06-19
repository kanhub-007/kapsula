"""Tests for the chunking pipeline (closes H5 coverage gap).

Black-box: exercises the documented contract of MarkdownChunker — it splits
content into token-bounded chunks, dispatches each element type to its
handler, and (H8) never infinite-loops or crashes on unknown element types.
Uses a FakeParser to avoid the unstructured dependency and keep the tests
fast and deterministic.
"""

from __future__ import annotations

from kapsula.infrastructure.repositories.chunking.chunk_pipeline import ChunkPipeline
from kapsula.infrastructure.repositories.chunking.chunk_state import ChunkState
from kapsula.infrastructure.repositories.chunking.content_block import ContentBlock
from kapsula.infrastructure.repositories.chunking.handlers.handler_registry import (
    HandlerRegistry,
)
from kapsula.infrastructure.repositories.chunking.markdown_chunker import (
    MarkdownChunker,
)


class FakeParser:
    """Returns a fixed list of ContentBlocks (no unstructured dependency)."""

    def __init__(self, elements: list[ContentBlock]):
        self._elements = elements

    def parse(self, content: str) -> list[ContentBlock]:
        return self._elements


def _blk(node_type: str, content: str, level: int = 0) -> ContentBlock:
    return ContentBlock(type=node_type, content=content, level=level)


class TestHandlerRegistry:
    def test_known_types_return_their_handler(self):
        registry = HandlerRegistry()
        for kind in ("title", "table", "list", "code", "text"):
            handler = registry.get(kind)
            assert handler is not None

    def test_unknown_type_falls_back_to_text_handler(self):
        # H8 regression guard: unknown element types must NOT raise KeyError.
        registry = HandlerRegistry()
        fallback = registry.get("narrative")
        default = registry.get("text")
        assert fallback is default


class TestMarkdownChunkerLoopSafety:
    def test_does_not_infinite_loop_when_handler_forgets_to_advance(self):
        # H8 regression guard: even a misbehaving handler cannot stall the
        # loop, because the loop owns index advancement.
        class StuckHandler:
            def handle(self, idx, elements, ctx):
                # Deliberately does NOT touch ctx.state.i.
                ctx.append(elements[idx].content)

        registry = HandlerRegistry()
        # Override 'text' with a handler that forgets to advance.
        registry._strategies["text"] = StuckHandler()

        parser = FakeParser([_blk("text", "alpha"), _blk("text", "beta")])
        chunker = MarkdownChunker(parser=parser, registry=registry)

        chunks = chunker.chunk("ignored")
        # Both elements were consumed (loop advanced past them).
        assert len(chunks) == 1
        assert "alpha" in chunks[0]["content"]
        assert "beta" in chunks[0]["content"]

    def test_text_elements_accumulate_into_one_chunk(self):
        parser = FakeParser(
            [
                _blk("title", "Heading", level=2),
                _blk("text", "first paragraph"),
                _blk("text", "second paragraph"),
            ]
        )
        chunker = MarkdownChunker(parser=parser)
        chunks = chunker.chunk("ignored")
        assert len(chunks) == 1
        assert "first paragraph" in chunks[0]["content"]
        assert "second paragraph" in chunks[0]["content"]

    def test_title_above_level_3_flushes_current_chunk(self):
        parser = FakeParser(
            [
                _blk("text", "intro text"),
                _blk("title", "Big Heading", level=1),
                _blk("text", "body text"),
            ]
        )
        chunker = MarkdownChunker(parser=parser)
        chunks = chunker.chunk("ignored")
        # intro flushed by the H1, then body forms a second chunk.
        assert len(chunks) == 2

    def test_code_block_becomes_atomic_chunk(self):
        parser = FakeParser([_blk("code", "print('hello')")])
        chunker = MarkdownChunker(parser=parser)
        chunks = chunker.chunk("ignored")
        assert len(chunks) == 1
        assert chunks[0]["metadata"]["node_type"] == "code"

    def test_unknown_element_type_is_treated_as_text(self):
        # H8: end-to-end — an unknown element type does not crash chunking.
        parser = FakeParser(
            [_blk("narrative", "a mystery element"), _blk("text", "normal")]
        )
        chunker = MarkdownChunker(parser=parser)
        chunks = chunker.chunk("ignored")
        assert len(chunks) == 1
        assert "mystery element" in chunks[0]["content"]


class TestChunkPipelineSplitLarge:
    def test_split_large_breaks_on_paragraph_boundaries(self):
        pipe = ChunkPipeline(
            max_tokens=1, hard_limit=1, encoding_name="cl100k_base", state=ChunkState()
        )
        # Two paragraphs; each exceeds 1 token so both become separate parts.
        parts = pipe._split_large("first para\n\nsecond para")
        assert parts == ["first para", "second para"]

    def test_empty_content_produces_no_chunks(self):
        pipe = ChunkPipeline(
            max_tokens=512,
            hard_limit=800,
            encoding_name="cl100k_base",
            state=ChunkState(),
        )
        pipe.flush()
        assert pipe.state.chunks == []
