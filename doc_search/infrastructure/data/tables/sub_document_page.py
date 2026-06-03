"""SubDocumentPage model."""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import UTC, datetime

from ..connection import Base

"""
Domain entity — represents a individual page within a sub-document in the document search system.

Uses SQLAlchemy ORM as the persistence mechanism.
In Clean Architecture, this serves as both the domain entity
and the persistence model. If migrating away from SQLAlchemy,
extract a pure dataclass and map between the two.
"""


class SubDocumentPage(Base):
    __tablename__ = "sub_document_pages"

    id = Column(Integer, primary_key=True, index=True)
    sub_document_id = Column(Integer, ForeignKey("sub_documents.id"), nullable=False)
    page_title = Column(String, nullable=False)
    breadcrumb_full = Column(String, nullable=False)
    content_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    sub_document = relationship("SubDocument", back_populates="pages")
