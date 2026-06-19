"""Upload processing strategies (infrastructure).

Concrete chunking + ingestion strategies and the upload pipeline. These
live in infrastructure because they orchestrate ORM writes, index
building, and filesystem I/O. The abstractions they implement
(:class:`ChunkingStrategy`, :class:`UploadIngestionStrategy`) live in the
domain layer; the pipeline context lives alongside these implementations.

This package is the resolution to the application→infrastructure layer
violation: previously these classes lived in ``core/application`` and
imported ORM/repository modules directly.
"""

from kapsula.infrastructure.repositories.processing.upload_strategies.fast_upload_ingestion_strategy import (
    FastUploadIngestionStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.flat_chunking_strategy import (
    FlatChunkingStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.full_upload_ingestion_strategy import (
    FullUploadIngestionStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.indexed_upload_ingestion_strategy import (
    IndexedUploadIngestionStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.subdocument_chunking_strategy import (
    SubDocumentChunkingStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.upload_ingestion_strategy_factory import (
    UploadIngestionStrategyFactory,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.upload_pipeline import (
    UploadPipeline,
)

__all__ = [
    "FastUploadIngestionStrategy",
    "FlatChunkingStrategy",
    "FullUploadIngestionStrategy",
    "IndexedUploadIngestionStrategy",
    "SubDocumentChunkingStrategy",
    "UploadIngestionStrategyFactory",
    "UploadPipeline",
]
