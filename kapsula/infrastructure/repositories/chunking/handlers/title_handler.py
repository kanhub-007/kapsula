"""Title element strategy."""


class TitleHandler:
    def handle(self, idx: int, elements: list, ctx) -> None:
        element = elements[idx]
        state = ctx.state

        if element.level <= 3:
            ctx.flush()

        while state.header_stack and state.header_stack[-1][0] >= element.level:
            state.header_stack.pop()
        state.header_stack.append((element.level, element.content))
        state.current_header = " > ".join(h[1] for h in state.header_stack)
        state.i = idx + 1
