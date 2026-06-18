"""Document structure skeleton extraction."""

import re

from kapsula.infrastructure.logging_config import get_logger

from .heading import Heading
from .markdown_utils import clean_markdown_link, split_breadcrumb_title
from .structure_node import StructureNode

logger = get_logger(__name__)


def extract_document_structure_skeleton(markdown_content: str) -> str:
    lines = markdown_content.split("\n")
    root = Heading(0, "Document Root")
    stack = [root]

    for line in lines:
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if heading_match:
            level = len(heading_match.group(1))
            text = clean_markdown_link(heading_match.group(2).strip())
            node = Heading(level, text)

            while stack and stack[-1].level >= level:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            stack.append(node)

    tree_root = StructureNode("root")
    for node in root.children:
        if node.level == 1 and "/" in node.text:
            tree_root.add_path(split_breadcrumb_title(node.text), node.children)
        else:
            tree_root.add_path([clean_markdown_link(node.text)], node.children)

    return "\n".join(["[DOCUMENT STRUCTURE]"] + tree_root.to_markdown(0))
