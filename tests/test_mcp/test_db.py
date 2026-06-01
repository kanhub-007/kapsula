"""Tests for MCP server foundation — db module."""

import pytest
from sqlalchemy import text
from doc_search.presentation.mcp.db import get_db_session


class TestGetDbSession:
    def test_returns_working_session(self):
        """Session factory should yield a usable SQLAlchemy session."""
        with get_db_session() as db:
            assert db is not None
            result = db.execute(text("SELECT 1")).scalar()
            assert result == 1

    def test_session_is_cleaned_up_after_context(self):
        """Session should be returned to the pool after context exits."""
        with get_db_session() as db:
            assert db is not None

        # After close(), we can get a new working session.
        with get_db_session() as db2:
            result = db2.execute(text("SELECT 1")).scalar()
            assert result == 1

    def test_session_cleanup_on_exception(self):
        """If an exception occurs, the session should still be cleaned up."""
        with pytest.raises(ValueError):
            with get_db_session() as db:
                _ = db  # reference only
                raise ValueError("test error")

        # Verify we can still get a new working session after the error
        with get_db_session() as db:
            result = db.execute(text("SELECT 1")).scalar()
            assert result == 1

    def test_multiple_sessions_are_independent(self):
        """Each call should produce a fresh, independent session."""
        with get_db_session() as db1, get_db_session() as db2:
            assert db1 is not db2
