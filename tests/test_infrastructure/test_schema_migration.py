"""Tests for the lightweight schema migration (C1).

Black-box: an existing database created with the *original* `library_cards`
schema (only the initial columns) must, after `init_db()`, expose every
column the ORM model declares and every column that query code filters on.
Previously the migration added only `description`, so any database created
before Phase 2 crashed at runtime on `card_type` / `importance` filters.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

# The columns the very first release of `library_cards` shipped with.
# Every other column was added later and must be back-filled by the migration.
_INITIAL_LIBRARY_CARD_COLUMNS = {
    "id",
    "collection_id",
    "document_id",
    "sub_document_id",
    "doc_id",
    "level",
    "title",
    "content",
    "extra_metadata",
    "created_at",
}

# Every column the current ORM model + query code relies on.
_REQUIRED_LIBRARY_CARD_COLUMNS = {
    "id",
    "collection_id",
    "document_id",
    "sub_document_id",
    "doc_id",
    "level",
    "title",
    "content",
    "extra_metadata",
    "created_at",
    # Phase 2 consolidation (filtered on by SqlConsolidationCardRepository,
    # ConsolidationRunner, MCP get_consolidation_status, get_library_cards)
    "card_type",
    "importance",
    "updated_at",
    "consolidation_run_id",
    # Slice 2 enrichment
    "description",
}


@pytest.fixture
def isolated_data_dir(monkeypatch, tmp_path):
    """Point the connection module at a throwaway data dir + engine.

    The module-level ``engine`` in ``connection.py`` binds to ``DATA_DIR`` at
    import time, so we patch ``DATA_DIR``/``DATABASE_URL`` and rebuild the
    engine + SessionLocal + Base registry for an isolated database.
    """
    db_file = tmp_path / "migration.db"
    monkeypatch.setattr(
        "kapsula.infrastructure.data.connection.DATA_DIR", str(tmp_path)
    )
    monkeypatch.setattr(
        "kapsula.infrastructure.data.connection.DATABASE_URL",
        f"sqlite:///{db_file}",
    )

    from sqlalchemy.orm import sessionmaker

    from kapsula.infrastructure.data import connection as conn_mod

    fresh_engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(conn_mod, "engine", fresh_engine)
    monkeypatch.setattr(conn_mod, "SessionLocal", sessionmaker(bind=fresh_engine))

    # Re-bind the shared declarative Base metadata to the fresh engine so
    # tables created during init_db land in the temp database.
    conn_mod.Base.metadata.bind = fresh_engine
    return fresh_engine


def _create_legacy_library_cards(engine):
    """Create the library_cards table with ONLY the initial columns."""
    with engine.begin() as conn:
        conn.execute(text("""
                CREATE TABLE library_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_id INTEGER,
                    document_id INTEGER,
                    sub_document_id INTEGER,
                    doc_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    extra_metadata TEXT,
                    created_at DATETIME
                )
                """))
        # A row written by the old schema — no card_type / importance etc.
        conn.execute(
            text(
                "INSERT INTO library_cards "
                "(doc_id, level, title, content) VALUES "
                "('legacy_1', 'level_2', 'Legacy', 'body')"
            )
        )


def test_migration_adds_all_missing_columns(isolated_data_dir):
    """An upgraded database must expose every required column (closes C1)."""
    engine = isolated_data_dir
    _create_legacy_library_cards(engine)

    before = {c["name"] for c in inspect(engine).get_columns("library_cards")}
    assert before == _INITIAL_LIBRARY_CARD_COLUMNS

    from kapsula.infrastructure.data.connection import init_db

    init_db()

    after = {c["name"] for c in inspect(engine).get_columns("library_cards")}
    missing = _REQUIRED_LIBRARY_CARD_COLUMNS - after
    assert not missing, f"Migration did not add columns: {missing}"


def test_migration_backfills_defaults_for_existing_rows(isolated_data_dir):
    """NOT NULL columns must get a DEFAULT so legacy rows stay valid (C1)."""
    engine = isolated_data_dir
    _create_legacy_library_cards(engine)

    from kapsula.infrastructure.data.connection import init_db

    init_db()

    from sqlalchemy import create_engine as _ce  # noqa: F401  (sanity alias)

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT card_type, importance FROM library_cards "
                "WHERE doc_id = 'legacy_1'"
            )
        ).first()
    assert row is not None
    # The ORM defaults must apply to the pre-existing row.
    assert row[0] == "extractive"
    assert row[1] == 0.5


def test_migration_is_idempotent(isolated_data_dir):
    """init_db() run twice must not error on already-added columns."""
    engine = isolated_data_dir
    _create_legacy_library_cards(engine)

    from kapsula.infrastructure.data.connection import init_db

    init_db()
    init_db()  # second run must be a no-op

    after = {c["name"] for c in inspect(engine).get_columns("library_cards")}
    assert _REQUIRED_LIBRARY_CARD_COLUMNS <= after
