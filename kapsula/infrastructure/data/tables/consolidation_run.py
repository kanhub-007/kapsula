"""ConsolidationRun model — tracks when consolidation was run on a collection."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from ..connection import Base


class ConsolidationRun(Base):
    __tablename__ = "consolidation_runs"

    id = Column(String, primary_key=True)  # UUID
    collection_id = Column(String, nullable=False)
    triggered_by = Column(String, nullable=False, default="manual")  # 'manual' | 'auto'
    cards_created = Column(Integer, nullable=False, default=0)
    cards_updated = Column(Integer, nullable=False, default=0)
    conflicts_found = Column(Integer, nullable=False, default=0)
    gaps_found = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
