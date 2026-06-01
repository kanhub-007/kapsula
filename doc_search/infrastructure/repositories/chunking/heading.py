"""Heading node for document structure hierarchy."""

from typing import List, Dict, Any


class Heading:
    def __init__(self, level: int, text: str):
        self.level = level
        self.text = text
        self.children: List["Heading"] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "text": self.text,
            "children": [child.to_dict() for child in self.children],
        }
