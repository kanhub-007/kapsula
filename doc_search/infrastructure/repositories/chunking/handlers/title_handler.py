"""Title element strategy."""

from typing import Any

from doc_search.core.domain.interfaces.element_handler import ElementHandler


class TitleHandler(ElementHandler):
    def handle(self, idx: int, elements: list, ctx: Any) -> None:
        el = elements[idx]
        s = ctx.state

        if el.level <= 3:
            ctx.flush()

        while s.header_stack and s.header_stack[-1][0] >= el.level:
            s.header_stack.pop()
        s.header_stack.append((el.level, el.content))
        s.current_header = " > ".join(h[1] for h in s.header_stack)
        s.i = idx + 1
