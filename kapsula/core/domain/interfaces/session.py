"""Persistence session protocol for the application layer.

The application layer depends on this abstract ``Session`` type instead of
``sqlalchemy.orm.Session`` so application code never imports SQLAlchemy
directly (closes the "Leaky Infrastructure" layer violation). Concrete
sessions are SQLAlchemy ``Session`` instances wired in the composition
root — they are duck-typed structural matches for this protocol, so no
adapter is needed at runtime.

Only the capability the application actually uses is declared here
(``commit`` / ``close``); the repository interfaces own all data access.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Session(Protocol):
    """Abstract persistence session.

    Implementations are SQLAlchemy ``Session`` objects (duck-typed) or any
    in-memory fake that exposes ``commit`` / ``close`` / ``rollback``.
    """

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


def is_session(obj: Any) -> bool:
    """Return True if *obj* quacks like a :class:`Session`."""
    return (
        hasattr(obj, "commit")
        and callable(obj.commit)
        and hasattr(obj, "close")
        and callable(obj.close)
    )
