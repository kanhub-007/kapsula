"""List element strategy."""

from typing import Any

from kapsula.core.domain.interfaces.element_handler import ElementHandler


class ListHandler(ElementHandler):
    def handle(self, idx: int, elements: list, ctx: Any) -> None:
        s = ctx.state
        items = [elements[idx].content]
        j = idx + 1
        while j < len(elements) and elements[j].type == "list":
            items.append(elements[j].content)
            j += 1

        content = "\n\n".join(items)
        tk = ctx.tk(content)

        if tk > ctx.hard_limit:
            if s.current:
                ctx.flush()
            ctx.add_parts(content)
        elif s.current_tokens + tk > ctx.max_tokens:
            ctx.flush()
            ctx.append(content)
        else:
            ctx.append(content)

        s.i = j
