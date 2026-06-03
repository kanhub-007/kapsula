"""Fast upload ingestion strategy."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FastUploadIngestionStrategy:
    """Parse, chunk, and save records without embedding or maintenance work."""

    mode: str = "fast"
    build_document_indexes: bool = False
    update_collection_summary: bool = False
    rebuild_aggregate_indexes: bool = False
