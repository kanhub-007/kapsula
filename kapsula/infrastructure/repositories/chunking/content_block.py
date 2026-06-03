"""Domain element produced by markdown parsing."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContentBlock:
    type: str  # "title", "table", "list", "code", "text"
    content: str
    level: int = 0
    html: str | None = None
