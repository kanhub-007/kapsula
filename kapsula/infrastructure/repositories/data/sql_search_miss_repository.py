"""SQLAlchemy-backed SearchMissLogRepository."""

from sqlalchemy.orm import Session

from kapsula.core.domain.interfaces.search_miss_repository import (
    SearchMissLogRepository,
)
from kapsula.infrastructure.data import SearchMissLog as OrmSearchMissLog
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

#: Maximum query length persisted (defensive truncation).
_MAX_QUERY_LEN = 500


class SqlSearchMissLogRepository(SearchMissLogRepository):
    """Persists search-miss rows for a collection."""

    def __init__(self, db: Session):
        self._db = db

    def log(
        self,
        collection_id: str,
        query: str,
        result_count: int,
        top_score: float,
    ) -> None:
        """Insert a search-miss row and commit."""
        self._db.add(
            OrmSearchMissLog(
                collection_id=collection_id,
                query=query[:_MAX_QUERY_LEN],
                result_count=result_count,
                top_score=top_score,
            )
        )
        self._db.commit()
