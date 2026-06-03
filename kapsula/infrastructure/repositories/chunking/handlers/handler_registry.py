"""Strategy registry — maps domain element types to strategies."""

from .title_handler import TitleHandler
from .table_handler import TableHandler
from .list_handler import ListHandler
from .code_handler import CodeHandler
from .text_handler import TextHandler


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
