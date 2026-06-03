"""Factory for upload ingestion strategies."""

from doc_search.core.application.dto.upload_ingestion_mode import UploadIngestionMode
from doc_search.core.application.use_cases.upload.fast_upload_ingestion_strategy import (
    FastUploadIngestionStrategy,
)
from doc_search.core.application.use_cases.upload.full_upload_ingestion_strategy import (
    FullUploadIngestionStrategy,
)
from doc_search.core.application.use_cases.upload.indexed_upload_ingestion_strategy import (
    IndexedUploadIngestionStrategy,
)
from doc_search.core.application.use_cases.upload.upload_ingestion_strategy import (
    UploadIngestionStrategy,
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
