"""Indexed upload ingestion strategy."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexedUploadIngestionStrategy:
    """Build document/sub-document indexes and defer collection maintenance."""

    mode: str = "indexed"
    build_document_indexes: bool = True
    update_collection_summary: bool = False
    rebuild_aggregate_indexes: bool = False
