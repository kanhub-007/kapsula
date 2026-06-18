"""Collection management MCP tools."""

import uuid

from fastmcp import FastMCP

from kapsula.core.domain.entities.collection import Collection
from kapsula.infrastructure.data import (
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

from ._shared import _get_db

# Library card level constants — the levels used for structural (extractive)
# heading cards: level_1=H3, level_2=H2, level_3=H1.
_STRUCTURAL_LEVELS = ("level_1", "level_2", "level_3")
_LEVEL_DISPLAY = {"level_3": "H1", "level_2": "H2", "level_1": "H3"}
_LEVEL_INDENT = {"level_3": "", "level_2": "  ", "level_1": "    "}

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
            extra = f" (account: {acc.name})" if account_id and acc else " (no account)"
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
                acc = (
                    db.query(OrmAccount).filter(OrmAccount.id == col.account_id).first()
                )
                if acc:
                    lines.append(f"Account: {acc.name} ({acc.account_id})")
            if card:
                lines.append(f"\nSummary: {card.content[:300]}")

            # Domain entities carry documents=[], so always load ORM for full list
            from kapsula.infrastructure.data import Collection as OrmCollection

            orm_col = db.query(OrmCollection).filter(OrmCollection.id == col.id).first()
            if orm_col and orm_col.documents:
                lines.append("\nDocuments:")
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
            # Bulk-load document counts to avoid N+1 queries
            from sqlalchemy import func

            from kapsula.infrastructure.data import Document as OrmDocument

            doc_counts = dict(
                db.query(OrmDocument.collection_id, func.count(OrmDocument.id))
                .filter(OrmDocument.collection_id.in_([c.id for c in collections]))
                .filter(OrmDocument.status != "archived")
                .group_by(OrmDocument.collection_id)
                .all()
            )
            for c in collections:
                card = _card_repo.find_collection_card(db, c.id) if c.id else None
                summary = card.content[:120] if card else "No summary"
                doc_count = doc_counts.get(c.id, 0)
                lines.append(f"  • {c.name} ({doc_count} docs) — {c.collection_id}")
                lines.append(f"    {summary}")
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="list_stale_maintenance",
        description=(
            "List collections that have stale (outdated) summaries, aggregate indexes, "
            "or consolidation state. Call this after deleting or uploading documents — "
            "those operations mark maintenance/consolidation as needed but defer heavy work. "
            "If a collection appears here, run run_collection_maintenance(collection_id) "
            "for that collection to refresh its summary, rebuild aggregate FAISS+BM25 indexes, "
            "and run the consolidation engine to generate topic cards."
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
                    f"consolidation_stale={state.get('consolidation_stale')} "
                    f"uploads_since_consolidation={state.get('uploads_since_consolidation', 0)} "
                    f"updated={state.get('updated_at', '?')}"
                )
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="run_collection_maintenance",
        description=(
            "Start background collection maintenance: refresh summary, "
            "rebuild FAISS+BM25 indexes, and run consolidation. "
            "Returns a maintenance_job_id immediately — poll progress "
            "with get_maintenance_job(job_id). "
            "This is the all-in-one repair and synthesis tool."
        ),
    )
    def run_collection_maintenance(collection_id: str) -> str:
        import threading

        db = _get_db()
        try:
            from kapsula.infrastructure.data import Collection as OrmCollection

            col = (
                db.query(OrmCollection)
                .filter(OrmCollection.collection_id == collection_id)
                .first()
            )
            if not col:
                return f"Collection not found: {collection_id}"

            from kapsula.presentation.upload.maintenance_runner import (
                get_maintenance_manager,
                run_maintenance_in_background,
            )

            manager = get_maintenance_manager()
            job = manager.create(
                collection_id=collection_id,
                collection_name=col.name,
            )

            threading.Thread(
                target=run_maintenance_in_background,
                args=(job.job_id, collection_id),
                daemon=True,
            ).start()

            return (
                f"Maintenance started for '{col.name}'\n"
                f"  maintenance_job_id: {job.job_id}\n"
                f'  Poll progress: get_maintenance_job("{job.job_id}")'
            )
        finally:
            db.close()

    @mcp.tool(
        name="get_maintenance_job",
        description=(
            "Poll a background maintenance job by job_id. "
            "Returns status, stage, progress, and result fields on completion. "
            "Use after run_collection_maintenance() to track progress."
        ),
    )
    def get_maintenance_job(job_id: str) -> str:
        from kapsula.presentation.upload.maintenance_runner import (
            get_maintenance_manager,
        )

        manager = get_maintenance_manager()
        job = manager.get(job_id)
        if not job:
            return f"Maintenance job not found: {job_id}"

        lines = [
            f"Maintenance Job: {job.job_id}",
            f"  Collection: {job.collection_name} ({job.collection_id})",
            f"  Status: {job.status}",
            f"  Stage: {job.stage}",
            f"  Progress: {job.progress}",
        ]
        if job.status == "completed":
            lines.append(f"  Summary updates: {job.summary_updates}")
            lines.append(f"  Summary failures: {job.summary_failures}")
            lines.append(f"  Collection FAISS: {job.collection_faiss or '--'}")
            lines.append(f"  Collection BM25: {job.collection_bm25 or '--'}")
            lines.append(f"  Account FAISS: {job.account_faiss or '--'}")
            lines.append(f"  Account BM25: {job.account_bm25 or '--'}")
            if job.cards_created or job.cards_updated:
                lines.append(
                    f"  Consolidation: {job.cards_created} created, "
                    f"{job.cards_updated} updated"
                )
            if job.cards_enriched:
                lines.append(f"  Cards enriched: {job.cards_enriched}")
        if job.error:
            lines.append(f"  Error: {job.error}")
        lines.append(f"  Created: {job.created_at.isoformat()}")
        lines.append(f"  Updated: {job.updated_at.isoformat()}")
        return "\n".join(lines)

    @mcp.tool(
        name="get_collection_maintenance_status",
        description=(
            "Show the most recent maintenance job for a collection. "
            "Returns last job_id, status, stage, and when it ran."
        ),
    )
    def get_collection_maintenance_status(collection_id: str) -> str:
        from kapsula.presentation.upload.maintenance_runner import (
            get_maintenance_manager,
        )

        manager = get_maintenance_manager()
        job = manager.get_latest_for_collection(collection_id)
        if not job:
            return f"No maintenance jobs found for collection: {collection_id}"

        lines = [
            f"Latest Maintenance — {job.collection_name}",
            f"  Job ID: {job.job_id}",
            f"  Status: {job.status}",
            f"  Stage: {job.stage}",
            f"  Created: {job.created_at.isoformat()}",
            f"  Updated: {job.updated_at.isoformat()}",
        ]
        if job.error:
            lines.append(f"  Error: {job.error}")
        return "\n".join(lines)

    @mcp.tool(
        name="get_library_cards",
        description=(
            "Browse the knowledge structure of a collection or document. "
            "Returns extractive H1/H2/H3 section cards with titles and content previews — "
            "like a table of contents with summaries. Use this BEFORE searching "
            "to understand what topics exist, then formulate a targeted search query. "
            "Filter by level ('level_1'=H3, 'level_2'=H2, 'level_3'=H1) or scope "
            "to one document via document_job_id. "
            "For synthesized topic/evolution/gap cards from consolidation, "
            "use get_consolidation_status(collection_id) to see what's available, "
            "then intelligent_search to query with topic card context."
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
            )
            from kapsula.infrastructure.data import (
                Document as OrmDocument,
            )
            from kapsula.infrastructure.data import (
                LibraryCard as OrmLibraryCard,
            )

            col = (
                db.query(OrmCollection)
                .filter(OrmCollection.collection_id == collection_id)
                .first()
            )
            if not col:
                return f"Collection not found: {collection_id}"

            q = db.query(OrmLibraryCard).filter(
                OrmLibraryCard.collection_id == col.id,
            )

            # Filter to structural levels only (exclude 'collection'/'document' summary cards).
            # When Phase 3 adds topic/evolution/gap cards (which use card_type not level),
            # this filter will need to include them for full knowledge browsing.
            if level:
                q = q.filter(OrmLibraryCard.level == level)
            else:
                q = q.filter(OrmLibraryCard.level.in_(_STRUCTURAL_LEVELS))

            # Optionally scope to one document
            if document_job_id:
                doc = (
                    db.query(OrmDocument)
                    .filter(OrmDocument.job_id == document_job_id)
                    .first()
                )
                if not doc:
                    return f"Document not found: {document_job_id}"
                q = q.filter(OrmLibraryCard.document_id == doc.id)

            cards = (
                q.order_by(
                    OrmLibraryCard.level.desc(),  # level_3 (H1) first
                    OrmLibraryCard.title,
                )
                .limit(limit)
                .all()
            )

            if not cards:
                return f"No library cards found in collection '{col.name}'."

            # Build document filename lookup
            doc_ids = set(c.document_id for c in cards if c.document_id)
            doc_names: dict[int, str] = {}
            if doc_ids:
                docs = db.query(OrmDocument).filter(OrmDocument.id.in_(doc_ids)).all()
                doc_names = {d.id: d.filename for d in docs}

            lines = [f"Library Cards — {col.name} ({len(cards)} cards)"]
            if level:
                lines[0] += f" [filtered: {_LEVEL_DISPLAY.get(level, level)}]"
            if document_job_id:
                doc_name = doc_names.get(doc.id, "?")
                lines[0] += f" [document: {doc_name}]"
            lines.append("")

            for card in cards:
                lvl_label = _LEVEL_DISPLAY.get(card.level, card.level)
                ind = _LEVEL_INDENT.get(card.level, "")
                doc_name = (
                    doc_names.get(card.document_id, "?") if card.document_id else "?"
                )
                preview = card.content[:200].replace("\n", " ").strip()
                desc = (
                    f" — {card.description}"
                    if getattr(card, "description", None)
                    else ""
                )
                lines.append(
                    f"{ind}[{lvl_label}] {card.title}{desc} — "
                    f'"{preview}..." ({doc_name})'
                )

            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="get_consolidation_status",
        description=(
            "Show consolidation state for a collection: when it last ran, "
            "how many topic/evolution/gap cards exist, and results of the "
            "last run. Use this to check the knowledge graph before searching."
        ),
    )
    def get_consolidation_status(collection_id: str) -> str:
        db = _get_db()
        try:
            from kapsula.infrastructure.data import (
                Collection as OrmCollection,
            )
            from kapsula.infrastructure.data import (
                ConsolidationRun,
            )
            from kapsula.infrastructure.data import (
                LibraryCard as OrmLibraryCard,
            )

            col = (
                db.query(OrmCollection)
                .filter(OrmCollection.collection_id == collection_id)
                .first()
            )
            if not col:
                return f"Collection not found: {collection_id}"

            topic_count = (
                db.query(OrmLibraryCard)
                .filter(
                    OrmLibraryCard.collection_id == col.id,
                    OrmLibraryCard.card_type == "topic",
                )
                .count()
            )
            evolution_count = (
                db.query(OrmLibraryCard)
                .filter(
                    OrmLibraryCard.collection_id == col.id,
                    OrmLibraryCard.card_type == "evolution",
                )
                .count()
            )
            gap_count = (
                db.query(OrmLibraryCard)
                .filter(
                    OrmLibraryCard.collection_id == col.id,
                    OrmLibraryCard.card_type == "gap",
                )
                .count()
            )

            last_run = (
                db.query(ConsolidationRun)
                .filter(ConsolidationRun.collection_id == collection_id)
                .order_by(ConsolidationRun.created_at.desc())
                .first()
            )

            lines = [
                f"Consolidation Status -- {col.name}",
                f"  Topic cards: {topic_count}",
                f"  Evolution cards: {evolution_count}",
                f"  Gap cards: {gap_count}",
            ]
            if last_run:
                lines.append(
                    f"  Last run: {last_run.created_at.isoformat() if last_run.created_at else '?'}"
                )
                lines.append(f"  Triggered by: {last_run.triggered_by}")
                lines.append(f"  Cards created: {last_run.cards_created}")
                lines.append(f"  Cards updated: {last_run.cards_updated}")
                lines.append(f"  Conflicts found: {last_run.conflicts_found}")
                lines.append(f"  Gaps found: {last_run.gaps_found}")
                if last_run.error:
                    lines.append(f"  Error: {last_run.error[:200]}")
            else:
                lines.append("  No consolidation run yet.")
            return "\n".join(lines)
        finally:
            db.close()
