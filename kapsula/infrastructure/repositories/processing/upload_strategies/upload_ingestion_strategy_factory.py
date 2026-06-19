"""Factory for upload ingestion strategies."""

from kapsula.core.domain.entities.upload_ingestion_mode import UploadIngestionMode
from kapsula.core.domain.interfaces.upload_ingestion_strategy import (
    UploadIngestionStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.fast_upload_ingestion_strategy import (
    FastUploadIngestionStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.full_upload_ingestion_strategy import (
    FullUploadIngestionStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.indexed_upload_ingestion_strategy import (
    IndexedUploadIngestionStrategy,
)


class UploadIngestionStrategyFactory:
    """Create upload ingestion strategies from user-provided mode strings."""

    @staticmethod
    def create(ingestion_mode: str | None) -> UploadIngestionStrategy:
        """Normalize an ingestion mode and return its strategy."""
        mode = UploadIngestionMode.normalize(ingestion_mode)
        if mode == UploadIngestionMode.FAST.value:
            return FastUploadIngestionStrategy()
        if mode == UploadIngestionMode.FULL.value:
            return FullUploadIngestionStrategy()
        return IndexedUploadIngestionStrategy()
