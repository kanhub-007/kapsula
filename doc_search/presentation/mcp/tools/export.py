"""Export MCP tools."""

from fastmcp import FastMCP

from doc_search.infrastructure.data import (
    LibraryCard,
    Collection,
)
from ._shared import _get_db, _resolve_collection, _resolve_account


def register_export_tools(mcp: FastMCP):
    @mcp.tool(
        name="export_account",
        description="Export complete account data: all collections, documents, and library cards.",
    )
    def export_account(account_id: str) -> str:
        db = _get_db()
        try:
            acc = _resolve_account(db, account_id)
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
                lines.append(f"  Documents: {len(col.documents)}")
                for doc in col.documents:
                    chunks = len(doc.chunks) if doc.chunks else 0
                    cards = (
                        db.query(LibraryCard)
                        .filter(
                            LibraryCard.document_id == doc.id,
                            LibraryCard.collection_id.is_(None),
                        )
                        .count()
                    )
                    lines.append(
                        f"  - {doc.filename} [{doc.status}] — {chunks} chunks, {cards} library cards — job_id={doc.job_id}"
                    )
                col_cards = (
                    db.query(LibraryCard)
                    .filter(
                        LibraryCard.collection_id == col.id,
                        LibraryCard.document_id.is_(None),
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
            col = _resolve_collection(db, collection_id)
            if not col:
                return f"Collection not found: {collection_id}"

            lines = [
                f"# Collection: {col.name}",
                f"collection_id: {col.collection_id}",
                f"Documents: {len(col.documents)}",
                f"Created: {col.created_at.isoformat() if col.created_at else '?'}",
                "",
            ]
            for doc in col.documents:
                chunks = len(doc.chunks) if doc.chunks else 0
                cards = (
                    db.query(LibraryCard)
                    .filter(
                        LibraryCard.document_id == doc.id,
                        LibraryCard.collection_id.is_(None),
                    )
                    .all()
                )
                lines.append(f"## Document: {doc.filename}")
                lines.append(
                    f"  Status: {doc.status}  |  Size: {doc.size} bytes  |  Chunks: {chunks}"
                )
                lines.append(f"  job_id: {doc.job_id}")
                if cards:
                    lines.append(f"  Library cards ({len(cards)}):")
                    for c in cards[:5]:
                        lines.append(f"    [{c.level}] {c.title}: {c.content[:150]}...")
                lines.append("")

            col_cards = (
                db.query(LibraryCard)
                .filter(
                    LibraryCard.collection_id == col.id,
                    LibraryCard.document_id.is_(None),
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
