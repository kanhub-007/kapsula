"""Collection management MCP tools."""

import uuid

from fastmcp import FastMCP

from doc_search.infrastructure.data import (
    Collection,
    Account,
    LibraryCard,
)
from ._shared import _get_db, _resolve_collection, _resolve_account


def register_collection_tools(mcp: FastMCP):
    @mcp.tool(
        name="create_collection",
        description="Create a new collection — a knowledge domain within an account (e.g., 'Dog Training', 'Project X', 'API Docs'). Collections group related documents so searches can be scoped to one domain for precision. Returns the collection GUID.",
    )
    def create_collection(name: str, account_id: str | None = None) -> str:
        db = _get_db()
        try:
            acc = None
            if account_id:
                acc = _resolve_account(db, account_id)
                if not acc:
                    return f"Account not found: {account_id}"

            collection_id = str(uuid.uuid4())
            col = Collection(
                collection_id=collection_id,
                name=name,
                account_id=acc.id if acc else None,
                ip_address="127.0.0.1",
            )
            db.add(col)
            db.commit()
            extra = f" (account: {acc.name})" if acc else " (no account)"
            return (
                f"Collection created: {name}{extra}\n  collection_id: {collection_id}"
            )
        finally:
            db.close()

    @mcp.tool(
        name="get_collection",
        description="Get collection details: name, library card summary, and a list of all documents with their filenames, statuses, chunk counts, and job_ids. Use the returned job_id values to target specific documents for deletion (delete_document) or detailed inspection (get_document_info).",
    )
    def get_collection(collection_id: str) -> str:
        db = _get_db()
        try:
            col = _resolve_collection(db, collection_id)
            if not col:
                return f"Collection not found: {collection_id}"

            card = (
                db.query(LibraryCard)
                .filter(
                    LibraryCard.collection_id == col.id,
                    LibraryCard.level == "collection",
                )
                .first()
            )

            lines = [
                f"Collection: {col.name}",
                f"collection_id: {col.collection_id}",
                f"Documents: {len(col.documents)}",
                f"Created: {col.created_at.isoformat() if col.created_at else '?'}",
            ]
            if col.account:
                lines.append(f"Account: {col.account.name} ({col.account.account_id})")
            if card:
                lines.append(f"\nSummary: {card.content[:300]}")
            if col.documents:
                lines.append("\nDocuments:")
                for d in col.documents:
                    lines.append(
                        f"  • {d.filename} [{d.status}] — {len(d.chunks)} chunks — job_id={d.job_id}"
                    )
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="list_collections",
        description="List all document collections with document counts and summaries.",
    )
    def list_collections(account_id: str | None = None) -> str:
        db = _get_db()
        try:
            q = db.query(Collection)
            if account_id:
                q = q.join(Account).filter(Account.account_id == account_id)
            collections = q.order_by(Collection.created_at.desc()).all()
            if not collections:
                return "No collections found."
            lines = [f"Collections ({len(collections)}):\n"]
            for c in collections:
                card = (
                    db.query(LibraryCard)
                    .filter(
                        LibraryCard.collection_id == c.id,
                        LibraryCard.level == "collection",
                    )
                    .first()
                )
                summary = card.content[:120] if card else "No summary"
                lines.append(
                    f"  • {c.name} ({len(c.documents)} docs) — {c.collection_id}"
                )
                lines.append(f"    {summary}")
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="list_stale_maintenance",
        description="List collections with deferred summary or aggregate-index maintenance.",
    )
    def list_stale_maintenance() -> str:
        db = _get_db()
        try:
            from doc_search.presentation.upload.maintenance_state_manager import (
                MaintenanceStateManager,
            )

            stale_states = MaintenanceStateManager().list_stale()
            if not stale_states:
                return "No stale maintenance state found."

            lines = [f"Stale maintenance states ({len(stale_states)}):\n"]
            for state in stale_states:
                account = None
                if state.get("account_db_id"):
                    account = (
                        db.query(Account)
                        .filter(Account.id == state["account_db_id"])
                        .first()
                    )
                lines.append(
                    "  • "
                    f"collection={state.get('collection_name') or state.get('collection_db_id')} "
                    f"({state.get('collection_id') or '?'}) "
                    f"account={account.name if account else '—'} "
                    f"summary_stale={state.get('summary_stale')} "
                    f"collection_index_stale={state.get('collection_index_stale')} "
                    f"account_index_stale={state.get('account_index_stale')} "
                    f"updated={state.get('updated_at', '?')}"
                )
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="run_collection_maintenance",
        description="Refresh a collection summary and rebuild collection/account aggregate indexes.",
    )
    def run_collection_maintenance(collection_id: str) -> str:
        db = _get_db()
        try:
            from doc_search.presentation.upload.collection_maintenance_runner import (
                CollectionMaintenanceRunner,
            )

            col = _resolve_collection(db, collection_id)
            if not col:
                return f"Collection not found: {collection_id}"
            result = CollectionMaintenanceRunner(db).run(col)
            return (
                "Collection maintenance completed\n"
                f"  Collection: {result['collection_name']}\n"
                f"  collection_id: {result['collection_id']}\n"
                f"  Summary updates: {result['summary_updates']}\n"
                f"  Summary failures: {result['summary_failures']}\n"
                f"  Collection FAISS: {result['collection_faiss'] or '—'}\n"
                f"  Collection BM25: {result['collection_bm25'] or '—'}\n"
                f"  Account FAISS: {result['account_faiss'] or '—'}\n"
                f"  Account BM25: {result['account_bm25'] or '—'}"
            )
        finally:
            db.close()
