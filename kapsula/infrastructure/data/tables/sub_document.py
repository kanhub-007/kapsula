"""SubDocument model — breadcrumb-based sub-documents for multi-index retrieval."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..connection import Base

"""
Domain entity — represents a breadcrumb-based sub-division of a document in the document search system.

Uses SQLAlchemy ORM as the persistence mechanism.
In Clean Architecture, this serves as both the domain entity
and the persistence model. If migrating away from SQLAlchemy,
extract a pure dataclass and map between the two.
"""


class SubDocument(Base):
    __tablename__ = "sub_documents"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    breadcrumb_key = Column(String, nullable=False, index=True)
    breadcrumb_level = Column(Integer, nullable=False)
    faiss_index_path = Column(String, nullable=True)
    bm25_index_path = Column(String, nullable=True)
    page_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    document = relationship("Document", back_populates="sub_documents")
    pages = relationship("SubDocumentPage", back_populates="sub_document")
    library_cards = relationship("LibraryCard", back_populates="sub_document")
    chunks = relationship("Chunk", back_populates="sub_document")
