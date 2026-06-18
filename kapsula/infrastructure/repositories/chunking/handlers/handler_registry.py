"""Strategy registry — maps domain element types to strategies."""

from .code_handler import CodeHandler
from .list_handler import ListHandler
from .table_handler import TableHandler
from .text_handler import TextHandler
from .title_handler import TitleHandler


class HandlerRegistry:
    """Maps element types to their handling strategies."""

    def __init__(self):
        self._strategies = {
            "title": TitleHandler(),
            "table": TableHandler(),
            "list": ListHandler(),
            "code": CodeHandler(),
            "text": TextHandler(),
        }

    def get(self, element_type: str):
        return self._strategies[element_type]
