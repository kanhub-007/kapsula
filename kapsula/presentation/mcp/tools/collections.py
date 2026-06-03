"""Collection management MCP tools."""

import uuid

from fastmcp import FastMCP

from kapsula.infrastructure.data import (
    LibraryCard as OrmLibraryCard,
    Account as OrmAccount,
)
from kapsula.infrastructure.repositories.data.sql_account_repository import (
    SqlAccountRepository,
)
from kapsula.infrastructure.repositories.data.sql_collection_repository import (
    SqlCollectionRepository,
)
from kapsula.infrastructure.repositories.data.sql_query_repositories import (
    SqlLibraryCardRepository,
)
from kapsula.core.domain.entities.collection import Collection
from ._shared import _get_db


_account_repo = SqlAccountRepository()
_collection_repo = SqlCollectionRepository()
_card_repo = SqlLibraryCardRepository()


def register_collection_tools(mcp: FastMCP):
    @mcp.tool(
        name="create_collection",
        description="Create a new collection — a knowledge domain within an account (e.g., 'Dog Training', 'Project X', 'API Docs'). Collections group related documents so searches can be scoped to one domain for precision. Returns the collection GUID.",
    )
    def create_collection(name: str, account_id: str | None = None) -> str:
        db = _get_db()
        try:
            acc_id = None
            if account_id:
                acc = _account_repo.find_by_account_id(db, account_id)
                if not acc:
                    return f"Account not found: {account_id}"
                acc_id = acc.id

            collection_id = str(uuid.uuid4())
            col = Collection(
                collection_id=collection_id,
                name=name,
                account_id=acc_id,
                ip_address="127.0.0.1",
            )
            _collection_repo.save(db, col)
            extra = f" (account: {account_id})" if account_id else " (no account)"
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
            col = _collection_repo.find_by_collection_id(db, collection_id)
            if not col:
                return f"Collection not found: {collection_id}"

            card = _card_repo.find_collection_card(db, col.id) if col.id else None

            lines = [
                f"Collection: {col.name}",
                f"collection_id: {col.collection_id}",
                f"Documents: {len(col.documents)}",
                f"Created: {col.created_at.isoformat() if col.created_at else '?'}",
            ]
            if col.account_id:
                acc = db.query(OrmAccount).filter(OrmAccount.id == col.account_id).first()
                if acc:
                    lines.append(f"Account: {acc.name} ({acc.account_id})")
            if card:
                lines.append(f"\nSummary: {card.content[:300]}")
            if col.documents:
                lines.append("\nDocuments:")
                # Domain collection has documents=[], need ORM for full load
                from kapsula.infrastructure.data import Collection as OrmCollection
                orm_col = db.query(OrmCollection).filter(OrmCollection.id == col.id).first()
                if orm_col:
                    for d in orm_col.documents:
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
            if account_id:
                collections = _collection_repo.list_by_account(db, account_id)
            else:
                collections = _collection_repo.list_all(db)
            if not collections:
                return "No collections found."
            lines = [f"Collections ({len(collections)}):\n"]
            for c in collections:
                card = _card_repo.find_collection_card(db, c.id) if c.id else None
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
        description=(
            "List collections that have stale (outdated) summaries or aggregate indexes. "
            "Call this after deleting documents or uploading new ones — those operations "
            "mark maintenance as needed but defer heavy work. If a collection appears here, "
            "run run_collection_maintenance(collection_id) for that collection to refresh "
            "its summary and rebuild its aggregate FAISS+BM25 indexes."
        ),
    )
    def list_stale_maintenance() -> str:
        db = _get_db()
        try:
            from kapsula.presentation.upload.maintenance_state_manager import (
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
                        db.query(OrmAccount)
                        .filter(OrmAccount.id == state["account_db_id"])
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
        description=(
            "Refresh a collection: regenerate its LLM summary and rebuild collection-level "
            "and account-level aggregate FAISS+BM25 indexes. Use when list_stale_maintenance() "
            "shows a collection needs maintenance, or when search results seem incomplete/outdated "
            "after deleting or uploading documents. This is the repair tool for stale indexes."
        ),
    )
    def run_collection_maintenance(collection_id: str) -> str:
        db = _get_db()
        try:
            from kapsula.presentation.upload.collection_maintenance_runner import (
                CollectionMaintenanceRunner,
            )
            from kapsula.infrastructure.data import Collection as OrmCollection

            col = db.query(OrmCollection).filter(OrmCollection.collection_id == collection_id).first()
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

    @mcp.tool(
        name="get_library_cards",
        description=(
            "Browse the knowledge structure of a collection or document. "
            "Returns H1/H2/H3 section cards with titles and content previews — "
            "like a table of contents with summaries. Use this BEFORE searching "
            "to understand what topics exist, then formulate a targeted search query. "
            "Filter by level ('level_1'=H3, 'level_2'=H2, 'level_3'=H1) or scope "
            "to one document via document_job_id."
        ),
    )
    def get_library_cards(
        collection_id: str,
        level: str | None = None,
        document_job_id: str | None = None,
        limit: int = 50,
    ) -> str:
        db = _get_db()
        try:
            from kapsula.infrastructure.data import (
                Collection as OrmCollection,
                LibraryCard as OrmLibraryCard,
                Document as OrmDocument,
            )

            col = db.query(OrmCollection).filter(
                OrmCollection.collection_id == collection_id
            ).first()
            if not col:
                return f"Collection not found: {collection_id}"

            q = db.query(OrmLibraryCard).filter(
                OrmLibraryCard.collection_id == col.id,
            )

            # Filter to structural levels only (exclude 'collection'/'document' summary cards)
            if level:
                q = q.filter(OrmLibraryCard.level == level)
            else:
                q = q.filter(
                    OrmLibraryCard.level.in_(['level_1', 'level_2', 'level_3'])
                )

            # Optionally scope to one document
            if document_job_id:
                doc = db.query(OrmDocument).filter(
                    OrmDocument.job_id == document_job_id
                ).first()
                if not doc:
                    return f"Document not found: {document_job_id}"
                q = q.filter(OrmLibraryCard.document_id == doc.id)

            cards = q.order_by(
                OrmLibraryCard.level.desc(),  # level_3 (H1) first
                OrmLibraryCard.title,
            ).limit(limit).all()

            if not cards:
                return f"No library cards found in collection '{col.name}'."

            # Group by level for structured output
            level_labels = {
                'level_3': 'H1',
                'level_2': 'H2',
                'level_1': 'H3',
            }

            # Build document filename lookup
            doc_ids = set(c.document_id for c in cards if c.document_id)
            doc_names: dict[int, str] = {}
            if doc_ids:
                docs = db.query(OrmDocument).filter(
                    OrmDocument.id.in_(doc_ids)
                ).all()
                doc_names = {d.id: d.filename for d in docs}

            lines = [
                f"Library Cards — {col.name} ({len(cards)} cards)"
            ]
            if level:
                lines[0] += f" [filtered: {level_labels.get(level, level)}]"
            if document_job_id:
                doc_name = doc_names.get(doc.id, "?") if doc else "?"
                lines[0] += f" [document: {doc_name}]"
            lines.append("")

            indent = {'level_3': '', 'level_2': '  ', 'level_1': '    '}
            for card in cards:
                lvl_label = level_labels.get(card.level, card.level)
                ind = indent.get(card.level, '')
                doc_name = doc_names.get(card.document_id, '?') if card.document_id else '?'
                preview = card.content[:200].replace('\n', ' ').strip()
                lines.append(
                    f"{ind}[{lvl_label}] {card.title} — "
                    f"\"{preview}...\" ({doc_name})"
                )

            return "\n".join(lines)
        finally:
            db.close()
