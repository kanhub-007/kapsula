"""Export MCP tools."""

from fastmcp import FastMCP

from doc_search.infrastructure.data import (
    LibraryCard as OrmLibraryCard,
    Collection as OrmCollection,
)
from doc_search.infrastructure.repositories.data.sql_account_repository import (
    SqlAccountRepository,
)
from doc_search.infrastructure.repositories.data.sql_collection_repository import (
    SqlCollectionRepository,
)
from doc_search.infrastructure.repositories.data.sql_document_repository import (
    SqlDocumentRepository,
)
from ._shared import _get_db


_account_repo = SqlAccountRepository()
_collection_repo = SqlCollectionRepository()
_doc_repo = SqlDocumentRepository()


def register_export_tools(mcp: FastMCP):
    @mcp.tool(
        name="export_account",
        description="Export complete account data: all collections, documents, and library cards.",
    )
    def export_account(account_id: str) -> str:
        db = _get_db()
        try:
            acc = _account_repo.find_by_account_id(db, account_id)
            if not acc:
                return f"Account not found: {account_id}"

            lines = [
                f"# Account: {acc.name}",
                f"account_id: {acc.account_id}",
                f"Created: {acc.created_at.isoformat() if acc.created_at else '?'}",
                f"Collections: {len(acc.collections)}",
                "",
            ]
            for col in acc.collections:
                lines.append(f"## Collection: {col.name} ({col.collection_id})")
                docs = _doc_repo.list_by_collection(db, col.collection_id)
                lines.append(f"  Documents: {len(docs)}")
                for doc in docs:
                    cards_count = (
                        db.query(OrmLibraryCard)
                        .filter(
                            OrmLibraryCard.document_id == doc.id,
                            OrmLibraryCard.collection_id.is_(None),
                        )
                        .count()
                    )
                    lines.append(
                        f"  - {doc.filename} [{doc.status}] — "
                        f"{len(doc.chunks)} chunks, {cards_count} cards — job_id={doc.job_id}"
                    )
                col_cards = (
                    db.query(OrmLibraryCard)
                    .filter(
                        OrmLibraryCard.collection_id == col.id,
                        OrmLibraryCard.document_id.is_(None),
                    )
                    .all()
                )
                if col_cards:
                    lines.append(f"  Collection-level cards: {len(col_cards)}")
                    for cc in col_cards[:3]:
                        lines.append(
                            f"    [{cc.level}] {cc.title}: {cc.content[:200]}..."
                        )
                lines.append("")
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="export_collection",
        description="Export complete collection data: all documents and library cards.",
    )
    def export_collection(collection_id: str) -> str:
        db = _get_db()
        try:
            col = _collection_repo.find_by_collection_id(db, collection_id)
            if not col:
                return f"Collection not found: {collection_id}"

            lines = [
                f"# Collection: {col.name}",
                f"collection_id: {col.collection_id}",
                f"Documents: {len(col.documents)}",
                f"Created: {col.created_at.isoformat() if col.created_at else '?'}",
                "",
            ]
            docs = _doc_repo.list_by_collection(db, collection_id)
            for doc in docs:
                cards = (
                    db.query(OrmLibraryCard)
                    .filter(
                        OrmLibraryCard.document_id == doc.id,
                        OrmLibraryCard.collection_id.is_(None),
                    )
                    .all()
                )
                lines.append(f"## Document: {doc.filename}")
                lines.append(
                    f"  Status: {doc.status}  |  Size: {doc.size} bytes  |  Chunks: {len(doc.chunks)}"
                )
                lines.append(f"  job_id: {doc.job_id}")
                if cards:
                    lines.append(f"  Library cards ({len(cards)}):")
                    for c in cards[:5]:
                        lines.append(f"    [{c.level}] {c.title}: {c.content[:150]}...")
                lines.append("")

            col_cards = (
                db.query(OrmLibraryCard)
                .filter(
                    OrmLibraryCard.collection_id == col.id,
                    OrmLibraryCard.document_id.is_(None),
                )
                .all()
            )
            if col_cards:
                lines.append("## Collection-level Library Cards")
                for cc in col_cards:
                    lines.append(f"  [{cc.level}] {cc.title}: {cc.content[:300]}...")
                lines.append("")
            return "\n".join(lines)
        finally:
            db.close()
