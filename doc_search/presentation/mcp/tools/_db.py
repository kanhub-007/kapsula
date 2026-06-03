"""Database access helpers for MCP tools."""

from doc_search.infrastructure.data import (
    SessionLocal,
    Collection,
    Account,
)


def _get_db():
    return SessionLocal()


def _resolve_collection(db, collection_id: str) -> Collection | None:
    return (
        db.query(Collection).filter(Collection.collection_id == collection_id).first()
    )


def _resolve_account(db, account_id: str) -> Account | None:
    return db.query(Account).filter(Account.account_id == account_id).first()
