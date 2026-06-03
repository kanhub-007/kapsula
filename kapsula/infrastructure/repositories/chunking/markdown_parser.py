"""Markdown parser — produces domain Elements from raw markdown."""

from typing import List

from unstructured.partition.md import partition_md

from .content_block import ContentBlock
from .element_adapter import adapt
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class MarkdownParser:
    """Parses markdown into domain Elements."""

    def parse(self, content: str) -> List[ContentBlock]:
        raw = partition_md(text=content)
        logger.info(f"Parsed {len(raw)} elements from markdown")

        return [self._to_content_block(el) for el in raw]

    @staticmethod
    def _to_content_block(el) -> ContentBlock:
        return ContentBlock(
            type=adapt(el),
            content=str(el),
            level=MarkdownParser._heading_level(el),
            html=MarkdownParser._get_html(el),
        )

    @staticmethod
    def _heading_level(el) -> int:
        if hasattr(el, "metadata") and el.metadata:
            if hasattr(el.metadata, "category_depth"):
                return el.metadata.category_depth
            if isinstance(el.metadata, dict) and "category_depth" in el.metadata:
                return el.metadata["category_depth"]
        return 0

    @staticmethod
    def _get_html(el) -> str | None:
        if not (hasattr(el, "metadata") and el.metadata):
            return None
        if hasattr(el.metadata, "text_as_html"):
            return el.metadata.text_as_html
        if isinstance(el.metadata, dict):
            return el.metadata.get("text_as_html")
        return None
