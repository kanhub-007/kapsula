"""LibraryCard model — parent sections for Russian Doll retrieval."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ..connection import Base


class LibraryCard(Base):
    __tablename__ = "library_cards"

    id = Column(Integer, primary_key=True, index=True)
    collection_id = Column(Integer, ForeignKey("collections.id"), nullable=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    sub_document_id = Column(Integer, ForeignKey("sub_documents.id"), nullable=True)
    doc_id = Column(String, nullable=False, index=True)
    level = Column(String, nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    extra_metadata = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    # Phase 2 consolidation columns (defaults preserve backward compatibility)
    card_type = Column(String, nullable=False, default="extractive")
    importance = Column(Float, nullable=False, default=0.5)
    updated_at = Column(DateTime, nullable=True)
    consolidation_run_id = Column(String, nullable=True)

    collection = relationship("Collection", back_populates="library_cards")
    document = relationship("Document", back_populates="library_cards")
    sub_document = relationship("SubDocument", back_populates="library_cards")
