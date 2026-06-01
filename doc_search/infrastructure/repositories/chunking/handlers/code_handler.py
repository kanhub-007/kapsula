"""Code element strategy."""

from typing import Any

from doc_search.core.domain.interfaces.element_handler import ElementHandler


class CodeHandler(ElementHandler):
    def handle(self, idx: int, elements: list, ctx: Any) -> None:
        el = elements[idx]
        s = ctx.state

        if s.current:
            ctx.flush()

        text = _with_next_if_small(elements, idx, el.content, ctx.tk)
        if text != el.content:
            idx += 1

        ctx.add_atomic(text, "code")
        s.chunk_start_header = s.current_header
        s.i = idx + 1


def _with_next_if_small(elements: list, idx: int, text: str, tk_fn) -> str:
    if idx + 1 < len(elements):
        nxt = elements[idx + 1]
        if nxt.type in ("text",):
            if tk_fn(nxt.content) < 100:
                return f"{text}\n\n{nxt.content}"
    return text
