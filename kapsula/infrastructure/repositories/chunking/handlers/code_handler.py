"""Code element strategy."""


class CodeHandler:
    def handle(self, idx: int, elements: list, ctx) -> None:
        element = elements[idx]
        state = ctx.state

        if state.current:
            ctx.flush()

        text = _with_next_if_small(elements, idx, element.content, ctx.tk)
        if text != element.content:
            idx += 1

        ctx.add_atomic(text, "code")
        state.chunk_start_header = state.current_header
        state.i = idx + 1


def _with_next_if_small(elements: list, idx: int, text: str, count_tokens) -> str:
    if idx + 1 < len(elements):
        nxt = elements[idx + 1]
        if nxt.type in ("text",):
            if count_tokens(nxt.content) < 100:
                return f"{text}\n\n{nxt.content}"
    return text
