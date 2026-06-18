"""Database connection and session management."""

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

# Repository-root ``data/`` directory. Computed via Path.parents for clarity
# and robustness against file relocation (closes SC7 — was 4× nested dirname).
DATA_DIR = str(Path(__file__).resolve().parents[3])
# NOTE: the directory is created lazily in init_db(), not at import time,
# so merely importing kapsula (e.g. in tests) has no filesystem side effect.

DATA_DIR = os.path.join(DATA_DIR, "data")

DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'documents.db')}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


# Enable WAL mode for concurrent reads during writes.
# Without WAL, writers block all readers, causing timeouts on concurrent access.
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """Create the data directory, all tables, and run lightweight migrations."""
    os.makedirs(DATA_DIR, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def _run_lightweight_migrations():
    """Add columns introduced after initial schema creation.

    SQLAlchemy's ``create_all`` only creates missing tables, not missing
    columns on existing tables. For SQLite we use ALTER TABLE ADD COLUMN,
    guarded by an introspection check so it is idempotent.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "library_cards" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("library_cards")}
    if "description" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE library_cards ADD COLUMN description TEXT"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
