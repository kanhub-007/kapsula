"""DTO for document deletion results."""

from dataclasses import dataclass, field


@dataclass
class DeleteDocumentResult:
    """Result of a document deletion operation."""

    job_id: str
    filename: str
    collection_name: str
    chunks_deleted: int
    rebuild: dict[str, str | None] = field(default_factory=dict)
    error: str | None = None

    @property
    def rebuild_lines(self) -> list[str]:
        """Human-readable rebuild status lines for presentation layers."""
        lines: list[str] = []
        if self.rebuild.get("collection_faiss"):
            bm25_ok = "rebuilt" if self.rebuild.get("collection_bm25") else "empty"
            lines.append(f"Collection aggregate: faiss=rebuilt, bm25={bm25_ok}")
        if self.rebuild.get("account_faiss"):
            bm25_ok = "rebuilt" if self.rebuild.get("account_bm25") else "empty"
            lines.append(f"Account aggregate: faiss=rebuilt, bm25={bm25_ok}")
        if self.error:
            lines.append(f"Aggregate rebuild failed: {self.error}")
        return lines
