"""List element strategy."""


class ListHandler:
    def handle(self, idx: int, elements: list, ctx) -> None:
        state = ctx.state
        items = [elements[idx].content]
        j = idx + 1
        while j < len(elements) and elements[j].type == "list":
            items.append(elements[j].content)
            j += 1

        content = "\n\n".join(items)
        token_count = ctx.tk(content)

        if token_count > ctx.hard_limit:
            if state.current:
                ctx.flush()
            ctx.add_parts(content)
        elif state.current_tokens + token_count > ctx.max_tokens:
            ctx.flush()
            ctx.append(content)
        else:
            ctx.append(content)

        state.i = j
