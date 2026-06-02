"""Tree node for building unique structure from headings."""

from typing import List


class StructureNode:
    def __init__(self, text: str):
        self.text = text
        self.children: dict[str, "StructureNode"] = {}

    def add_path(self, path_parts: List[str], remaining_children: List = None):
        if not path_parts:
            if remaining_children:
                for child in remaining_children:
                    child_text = _clean_link(child.text)
                    if child_text not in self.children:
                        self.children[child_text] = StructureNode(child_text)
                    if child.children:
                        self.children[child_text].add_path([], child.children)
            return

        current = path_parts[0]
        rest = path_parts[1:]
        if current not in self.children:
            self.children[current] = StructureNode(current)
        self.children[current].add_path(rest, remaining_children)

    def to_markdown(self, depth: int = 0, parent_text: str = "") -> List[str]:
        lines = []
        for child_text in sorted(self.children.keys()):
            child = self.children[child_text]
            if parent_text and child_text.lower() == parent_text.lower():
                if child.children:
                    lines.extend(child.to_markdown(depth, parent_text))
                continue

            prefix = "  " * depth
            heading_level = min(depth + 1, 6)
            lines.append(f"{prefix}- {'#' * heading_level} {child_text}")
            if child.children:
                lines.extend(child.to_markdown(depth + 1, child_text))
        return lines


def _clean_link(text: str) -> str:
    import re

    text = re.sub(r"\[([^\]]*)\]\([^\)]*\)", r"\1", text)
    text = re.sub(r"^\[\]\([^\)]*\)", "", text)
    text = re.sub(r"\*\*([^\*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^\*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    return text.strip()
