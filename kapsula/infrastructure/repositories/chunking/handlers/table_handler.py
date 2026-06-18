"""Table element strategy."""

from ..table_parser import transform_table_to_text


class TableHandler:
    def handle(self, idx: int, elements: list, ctx) -> None:
        element = elements[idx]
        state = ctx.state
        ctx.flush()

        text = (
            transform_table_to_text(element.html) if element.html else element.content
        )
        text = _with_next_if_small(elements, idx, text, ctx.tk)
        if text != element.content:
            idx += 1

        ctx.add_atomic(text, "table")
        state.chunk_start_header = state.current_header
        state.i = idx + 1


def _with_next_if_small(elements: list, idx: int, text: str, count_tokens) -> str:
    if idx + 1 < len(elements):
        nxt = elements[idx + 1]
        if nxt.type in ("text",):
            if count_tokens(nxt.content) < 100:
                return f"{text}\n\n{nxt.content}"
    return text
