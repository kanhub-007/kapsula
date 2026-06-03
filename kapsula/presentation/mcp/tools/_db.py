"""Database access helpers for MCP tools."""

from kapsula.infrastructure.data import (
    Collection as OrmCollection,
    Account as OrmAccount,
    SessionLocal,
)


def _get_db():
    return SessionLocal()


def _resolve_collection(db, collection_id: str):
    return (
        db.query(OrmCollection)
        .filter(OrmCollection.collection_id == collection_id)
        .first()
    )


def _resolve_account(db, account_id: str):
    return (
        db.query(OrmAccount)
        .filter(OrmAccount.account_id == account_id)
        .first()
    )
