"""Upload ingestion mode value object."""

from enum import StrEnum


class UploadIngestionMode(StrEnum):
    """Supported upload ingestion modes."""

    FAST = "fast"
    INDEXED = "indexed"
    FULL = "full"

    @classmethod
    def normalize(cls, value: str | None) -> str:
        """Normalize and validate an upload ingestion mode string."""
        mode = (value or cls.INDEXED.value).strip().lower()
        if mode == "maintenance":
            raise ValueError(
                "ingestion_mode='maintenance' is reserved for maintenance tools "
                "and cannot be used for document upload"
            )
        try:
            return cls(mode).value
        except ValueError as exc:
            allowed = ", ".join(sorted(item.value for item in cls))
            raise ValueError(
                f"Unsupported ingestion_mode '{value}'. Allowed values: {allowed}"
            ) from exc
