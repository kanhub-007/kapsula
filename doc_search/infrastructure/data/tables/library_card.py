"""LibraryCard model — parent sections for Russian Doll retrieval."""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import UTC, datetime

from ..connection import Base

"""
Domain entity — represents a parent section used for context expansion in the document search system.

Uses SQLAlchemy ORM as the persistence mechanism.
In Clean Architecture, this serves as both the domain entity
and the persistence model. If migrating away from SQLAlchemy,
extract a pure dataclass and map between the two.
"""


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

    collection = relationship("Collection", back_populates="library_cards")
    document = relationship("Document", back_populates="library_cards")
    sub_document = relationship("SubDocument", back_populates="library_cards")
