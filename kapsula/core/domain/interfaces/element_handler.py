"""Element handler protocol."""

from typing import Any, Protocol


class ElementHandler(Protocol):
    def handle(self, idx: int, elements: list, ctx: Any) -> None: ...
