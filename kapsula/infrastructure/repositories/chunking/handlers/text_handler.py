"""Text element strategy."""

from typing import Any

from kapsula.core.domain.interfaces.element_handler import ElementHandler


class TextHandler(ElementHandler):
    def handle(self, idx: int, elements: list, ctx: Any) -> None:
        el = elements[idx]
        s = ctx.state
        tk = ctx.tk(el.content)

        if s.current_tokens + tk > ctx.max_tokens:
            ctx.flush()

        ctx.append(el.content)
        s.i = idx + 1
