"""Element handler protocol."""

from typing import Protocol, Any


class ElementHandler(Protocol):
    def handle(self, idx: int, elements: list, ctx: Any) -> None: ...
