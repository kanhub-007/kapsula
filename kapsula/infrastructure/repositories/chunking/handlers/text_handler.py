"""Text element strategy."""


class TextHandler:
    def handle(self, idx: int, elements: list, ctx) -> None:
        element = elements[idx]
        state = ctx.state
        token_count = ctx.tk(element.content)

        if state.current_tokens + token_count > ctx.max_tokens:
            ctx.flush()

        ctx.append(element.content)
        state.i = idx + 1
