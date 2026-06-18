"""Heading node for document structure hierarchy."""

from typing import Any


class Heading:
    def __init__(self, level: int, text: str):
        self.level = level
        self.text = text
        self.children: list[Heading] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "text": self.text,
            "children": [child.to_dict() for child in self.children],
        }
