"""Document model."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ..connection import Base

# ORM persistence model for Document. Mapped to/from the pure domain entity
# ``kapsula.core.domain.entities.document.Document`` via
# ``kapsula.infrastructure.repositories.data.mappers``.


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, unique=True, nullable=False, index=True)
    collection_id = Column(Integer, ForeignKey("collections.id"), nullable=False)
    filename = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    ip_address = Column(String, nullable=False)
    duration = Column(Float, nullable=True)
    content = Column(Text, nullable=False)
    status = Column(String, default="processing")
    doc_state = Column(String, default="active")  # active | archived
    faiss_index_path = Column(String, nullable=True)
    bm25_index_path = Column(String, nullable=True)

    collection = relationship("Collection", back_populates="documents")
    structure = relationship(
        "DocumentStructure", back_populates="document", uselist=False
    )
    chunks = relationship("Chunk", back_populates="document")
    library_cards = relationship("LibraryCard", back_populates="document")
    sub_documents = relationship("SubDocument", back_populates="document")
