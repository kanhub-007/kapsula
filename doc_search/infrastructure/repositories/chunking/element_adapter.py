"""Adapter from unstructured element types to domain element types."""

from .code_detector import is_code_block


def adapt(el) -> str:
    """Return domain element type from an unstructured element."""
    el_type = type(el).__name__

    if "Title" in el_type:
        return "title"
    if "Table" in el_type:
        return "table"
    if "ListItem" in el_type:
        return "list"
    if "Code" in el_type or is_code_block(str(el)):
        return "code"
    return "text"
