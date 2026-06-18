"""Search routes — re-exports from split modules.

.. note:: This file is kept for backward compatibility. New imports should use
   the sub-modules directly: search_collection, search_document, search_intelligent.
"""

# ruff: noqa: F401

from .search_collection import router
from .search_document import router as search_document_router
from .search_intelligent import router as search_intelligent_router
from .search_helpers import extract_citation_from_result
