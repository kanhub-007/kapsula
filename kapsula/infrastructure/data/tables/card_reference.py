"""CardReference model — links topic/evolution/gap cards to their source extractive cards."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..connection import Base


class CardReference(Base):
    __tablename__ = "card_references"

    source_card_id = Column(Integer, ForeignKey("library_cards.id"), primary_key=True)
    target_card_id = Column(Integer, ForeignKey("library_cards.id"), primary_key=True)
    relation_type = Column(
        String, nullable=False
    )  # 'synthesizes_from', 'contradicts', 'extends', 'deprecates'
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    source_card = relationship("LibraryCard", foreign_keys=[source_card_id])
    target_card = relationship("LibraryCard", foreign_keys=[target_card_id])
