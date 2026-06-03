"""SearchMissLog model — logs searches with few results for gap detection."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from ..connection import Base


class SearchMissLog(Base):
    __tablename__ = "search_miss_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(String, nullable=True)
    query = Column(Text, nullable=False)
    result_count = Column(Integer, nullable=False)
    top_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
