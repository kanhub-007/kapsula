"""Account model."""

from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import UTC, datetime

from ..connection import Base

"""
Domain entity — represents a user/organization account in the document search system.

Uses SQLAlchemy ORM as the persistence mechanism.
In Clean Architecture, this serves as both the domain entity
and the persistence model. If migrating away from SQLAlchemy,
extract a pure dataclass and map between the two.
"""


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    ip_address = Column(String, nullable=False)

    collections = relationship("Collection", back_populates="account")
