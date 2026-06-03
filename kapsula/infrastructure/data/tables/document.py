"""Document model."""

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import UTC, datetime

from ..connection import Base

"""
Domain entity — represents a uploaded markdown document in the document search system.

Uses SQLAlchemy ORM as the persistence mechanism.
In Clean Architecture, this serves as both the domain entity
and the persistence model. If migrating away from SQLAlchemy,
extract a pure dataclass and map between the two.
"""


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
