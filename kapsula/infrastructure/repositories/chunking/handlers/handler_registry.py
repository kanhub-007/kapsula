"""Strategy registry — maps domain element types to strategies."""

from .code_handler import CodeHandler
from .list_handler import ListHandler
from .table_handler import TableHandler
from .text_handler import TextHandler
from .title_handler import TitleHandler


class HandlerRegistry:
    """Maps element types to their handling strategies.

    Unknown element types fall back to the :class:`TextHandler` (closes H8)
    instead of raising ``KeyError`` and aborting the whole document's
    chunking. ``unstructured`` can occasionally emit a niche element type
    we have no dedicated handler for; treating it as text is the safe
    default that never drops content or crashes the pipeline.
    """

    def __init__(self):
        self._strategies = {
            "title": TitleHandler(),
            "table": TableHandler(),
            "list": ListHandler(),
            "code": CodeHandler(),
            "text": TextHandler(),
        }
        self._default = self._strategies["text"]

    def get(self, element_type: str):
        """Return the handler for *element_type*, or the text handler."""
        return self._strategies.get(element_type, self._default)
