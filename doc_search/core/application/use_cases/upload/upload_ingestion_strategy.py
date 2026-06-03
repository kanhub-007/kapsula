"""Upload ingestion strategy interface."""

from typing import Protocol


class UploadIngestionStrategy(Protocol):
    """Defines behavior switches for a document upload mode."""

    mode: str
    build_document_indexes: bool
    update_collection_summary: bool
    rebuild_aggregate_indexes: bool
