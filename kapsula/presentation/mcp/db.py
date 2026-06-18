"""Database session management for MCP server context.

Provides a context manager for DB sessions outside of FastAPI's
dependency injection system.
"""

from collections.abc import Generator
from contextlib import contextmanager

from kapsula.infrastructure.data import SessionLocal


@contextmanager
def get_db_session() -> Generator:
    """Yield a SQLAlchemy session, ensuring cleanup on exit.

    Usage:
        with get_db_session() as db:
            result = db.query(Document).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
