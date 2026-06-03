"""Full upload ingestion strategy."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FullUploadIngestionStrategy:
    """Build indexes and run collection/account maintenance before completion."""

    mode: str = "full"
    build_document_indexes: bool = True
    update_collection_summary: bool = True
    rebuild_aggregate_indexes: bool = True
