"""Chunk model."""

from datetime import UTC, datetime

from sqlalchemy import Column, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from ..connection import Base

"""
Domain entity — represents a token-bounded segment of document content in the document search system.

Uses SQLAlchemy ORM as the persistence mechanism.
In Clean Architecture, this serves as both the domain entity
and the persistence model. If migrating away from SQLAlchemy,
extract a pure dataclass and map between the two.
"""


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    sub_document_id = Column(Integer, ForeignKey("sub_documents.id"), nullable=True)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=True)
    chunk_metadata = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    document = relationship("Document", back_populates="chunks")
    sub_document = relationship("SubDocument", back_populates="chunks")
