"""Interface for starting background document processing."""

from abc import ABC, abstractmethod


class BackgroundProcessor(ABC):
    """Starts background processing for a newly uploaded document."""

    @abstractmethod
    def start_processing(
        self,
        job_id: str,
        content: str,
        max_tokens: int,
        ingestion_mode: str,
    ) -> None:
        """Begin background chunking, embedding, and indexing.

        Args:
            job_id: The GUID for the new document.
            content: Raw markdown content.
            max_tokens: Maximum tokens per chunk.
            ingestion_mode: fast | indexed | full.
        """
