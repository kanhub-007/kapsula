"""Collection model."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..connection import Base

"""
Domain entity — represents a group of related documents in the document search system.

Uses SQLAlchemy ORM as the persistence mechanism.
In Clean Architecture, this serves as both the domain entity
and the persistence model. If migrating away from SQLAlchemy,
extract a pure dataclass and map between the two.
"""


class Collection(Base):
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True, index=True)
    collection_id = Column(String, unique=True, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    name = Column(String, nullable=False)
    logo_filename = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    ip_address = Column(String, nullable=False)

    account = relationship("Account", back_populates="collections")
    documents = relationship("Document", back_populates="collection")
    library_cards = relationship("LibraryCard", back_populates="collection")
