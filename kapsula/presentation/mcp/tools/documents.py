"""Document management MCP tools."""

import json

from fastmcp import FastMCP

from kapsula.infrastructure.data import (
    DocumentStructure as OrmDocumentStructure,
)
from kapsula.infrastructure.repositories.data.sql_document_repository import (
    SqlDocumentRepository,
)
from kapsula.infrastructure.repositories.data.sql_query_repositories import (
    SqlChunkRepository,
)
from ._shared import _get_db

_doc_repo = SqlDocumentRepository()
_chunk_repo = SqlChunkRepository()


def register_document_tools(mcp: FastMCP):
    @mcp.tool(
        name="upload_document",
        description=(
            "Upload a markdown (.md) file to a collection as a memory document. "
            "Use well-structured markdown with H2/H3 headings — the chunker splits on headings, "
            "and each heading becomes a library card for navigation and context expansion. "
            "Without proper H2/H3 headings, the browse-before-search workflow breaks down: "
            "get_library_cards() will have nothing to show, context expansion won't work, "
            "and intelligent_search loses its section-level targeting. "
            "Sizing guidance: stable interconnected knowledge = medium doc (1-5 pages); "
            "frequently changing facts = small doc (1-3 paragraphs); "
            "reference tables/dosages/configs = separate small doc. "
            "ingestion_mode: fast (no indexes), indexed (default, FAISS+BM25), or full (indexes + aggregates + summary). "
            "Returns a job_id for progress tracking. "
            "To update knowledge later: get the old document's job_id from get_collection(), delete it, then re-upload."
        ),
    )
    def upload_document(
        file_path: str,
        collection_id: str,
        max_tokens: int = 512,
        ingestion_mode: str = "indexed",
    ) -> str:
        from kapsula.startup import create_upload_document_use_case

        db = _get_db()
        try:
            use_case = create_upload_document_use_case()
            result = use_case.execute(
                db, file_path, collection_id, max_tokens, ingestion_mode
            )
            # Mark consolidation as stale after successful upload
            try:
                from kapsula.presentation.upload.maintenance_state_manager import (
                    MaintenanceStateManager,
                )

                MaintenanceStateManager().increment_uploads(collection_id)
            except Exception:
                pass  # best-effort: don't break the tool on state-tracking failure
        except ValueError as exc:
            return f"Error: {exc}"
        finally:
            db.close()

        return (
            f"Uploaded: {result.filename}\n"
            f"  Collection: {result.collection_name}\n"
            f"  job_id: {result.job_id}\n"
            f"  Status: {result.status}\n"
            f"  Ingestion mode: {result.ingestion_mode}"
        )

    @mcp.tool(
        name="delete_document",
        description=(
            "Soft-delete a document from a collection by job_id. "
            "Archives the document, removes all its chunks from the database, "
            "deletes document-level and aggregate index files, and rebuilds "
            "collection and account aggregate indexes. "
            "Use get_collection() first to find the job_id for the document you want to remove. "
            "This is the intended path for updating knowledge: delete old version, then re-upload."
        ),
    )
    def delete_document(job_id: str) -> str:
        from kapsula.startup import create_delete_document_use_case

        db = _get_db()
        try:
            # Look up collection_id before deletion so we can mark consolidation stale
            from kapsula.infrastructure.data import Document as OrmDocument

            orm_doc = db.query(OrmDocument).filter(OrmDocument.job_id == job_id).first()
            collection_id = (
                orm_doc.collection.collection_id
                if orm_doc and orm_doc.collection
                else None
            )

            use_case = create_delete_document_use_case()
            result = use_case.execute(db, job_id)
            # Mark consolidation as stale after successful deletion
            if collection_id:
                try:
                    from kapsula.presentation.upload.maintenance_state_manager import (
                        MaintenanceStateManager,
                    )

                    MaintenanceStateManager().increment_uploads(collection_id)
                except Exception:
                    pass  # best-effort
        except ValueError as exc:
            return str(exc)
        finally:
            db.close()

        msg = (
            f"Document deleted: {result.filename}\n"
            f"  job_id: {result.job_id}\n"
            f"  Collection: {result.collection_name}\n"
            f"  Chunks removed: {result.chunks_deleted}\n"
            f"  State: archived (soft delete)"
        )
        if result.rebuild_lines:
            msg += "\n  " + "\n  ".join(result.rebuild_lines)
        return msg

    @mcp.tool(
        name="list_documents",
        description="List uploaded documents with status and chunk counts. Optionally filter by collection.",
    )
    def list_documents(collection_id: str | None = None) -> str:
        db = _get_db()
        try:
            if collection_id:
                from kapsula.infrastructure.data import Collection as OrmCollection

                col = (
                    db.query(OrmCollection)
                    .filter(OrmCollection.collection_id == collection_id)
                    .first()
                )
                if not col:
                    return f"Collection not found: {collection_id}"
                docs = _doc_repo.list_by_collection(db, collection_id)
            else:
                docs = _doc_repo.list_all(db)
            if not docs:
                return "No documents found."

            lines = [f"Documents ({len(docs)}):\n"]
            for d in docs:
                chunks_count = _chunk_repo.count_by_document(db, d.id) if d.id else 0
                lines.append(f"  • {d.filename} [{d.status}] — {chunks_count} chunks")
                lines.append(f"    job_id: {d.job_id}")
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="list_collection_documents",
        description="Compact document list for one collection with names, statuses, chunk counts, and job_id values.",
    )
    def list_collection_documents(collection_id: str) -> str:
        db = _get_db()
        try:
            docs = _doc_repo.list_by_collection(db, collection_id)
            if not docs:
                return f"No documents found in collection: {collection_id}"
            lines = [f"Documents in collection ({len(docs)}):\n"]
            for d in docs:
                chunks_count = _chunk_repo.count_by_document(db, d.id) if d.id else 0
                lines.append(
                    f"  • {d.filename} [{d.status}] — chunks={chunks_count} — job_id={d.job_id}"
                )
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="get_document_info",
        description="Get document details: status, structure skeleton, and chunk previews.",
    )
    def get_document_info(job_id: str) -> str:
        db = _get_db()
        try:
            doc = _doc_repo.find_document_by_job_id(db, job_id)
            if not doc:
                return f"Document not found: {job_id}"

            structure = None
            if doc.id:
                structure = (
                    db.query(OrmDocumentStructure)
                    .filter(OrmDocumentStructure.document_id == doc.id)
                    .first()
                )

            chunks = _chunk_repo.list_by_document(db, doc.id) if doc.id else []

            lines = [
                f"Document: {doc.filename}",
                f"Status: {doc.status}",
                f"Size: {doc.size} bytes",
                f"Chunks: {len(chunks)}",
                f"Duration: {doc.duration:.2f}s" if doc.duration else "Duration: —",
                f"Created: {doc.created_at.isoformat() if doc.created_at else '?'}",
                f"job_id: {doc.job_id}",
            ]
            if structure and structure.skeleton_structure:
                lines.append("\n--- Structure (first 1000 chars) ---")
                lines.append(structure.skeleton_structure[:1000])
            if chunks:
                lines.append("\n--- First 3 Chunks ---")
                for ch in chunks[:3]:
                    preview = ch.content[:300].replace("\n", " ")
                    lines.append(
                        f"  [{ch.chunk_index}] ({ch.token_count} tokens): {preview}..."
                    )
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="get_document_progress",
        description="Check the real-time processing progress of an uploaded document.",
    )
    def get_document_progress(job_id: str) -> str:
        db = _get_db()
        try:
            doc = _doc_repo.find_document_by_job_id(db, job_id)
            if not doc:
                return f"Document not found: {job_id}"

            from kapsula.presentation.api.tasks import get_processing_status
            from kapsula.presentation.upload.stale_progress_guard import (
                StaleProgressGuard,
            )

            status = get_processing_status(job_id)
            chunks_count = _chunk_repo.count_by_document(db, doc.id) if doc.id else 0

            if status:
                live_progress = int(status.get("progress", 0) or 0)
                live_status = status.get("status")
                live_stage = status.get("stage")
                terminal_override = StaleProgressGuard.terminal_override(
                    document_status=doc.status,
                    live_status=live_status,
                    live_stage=live_stage,
                    live_progress=live_progress,
                    chunk_count=chunks_count,
                    duration=doc.duration,
                )
                if terminal_override:
                    return (
                        f"Document: {doc.filename}\n"
                        f"Status: {terminal_override['status']}\n"
                        f"Progress: {terminal_override['progress']}%\n"
                        f"Stage: {terminal_override['stage']}\n"
                        f"Message: {terminal_override['message']}\n"
                        f"Chunks: {terminal_override.get('chunk_count', '—')}\n"
                        f"Duration: {terminal_override.get('duration') or '—'}"
                    )
                return (
                    f"Document: {doc.filename}\n"
                    f"Status: {status.get('status', '?')}\n"
                    f"Progress: {status.get('progress', 0)}%\n"
                    f"Stage: {status.get('stage', '?')}\n"
                    f"Message: {status.get('message', '')}\n"
                    f"Ingestion mode: {status.get('ingestion_mode', '—')}\n"
                    f"Chunks: {status.get('chunk_count', '—')}\n"
                    f"Duration: {status.get('duration', '—')}"
                )
            return f"Document: {doc.filename}\nStatus: {doc.status} (no live progress)"
        finally:
            db.close()

    @mcp.tool(
        name="download_document_chunks",
        description="Export all chunks of a document as formatted text with chunk indices and metadata.",
    )
    def download_document_chunks(job_id: str) -> str:
        db = _get_db()
        try:
            doc = _doc_repo.find_document_by_job_id(db, job_id)
            if not doc:
                return f"Document not found: {job_id}"
            if doc.status != "completed":
                return f"Document not ready. Status: {doc.status}"

            chunks = _chunk_repo.list_by_document(db, doc.id) if doc.id else []

            lines = [
                f"Document: {doc.filename}",
                f"Total chunks: {len(chunks)}",
                f"job_id: {doc.job_id}",
                "",
            ]
            for ch in chunks:
                meta = {}
                if ch.chunk_metadata:
                    try:
                        meta = json.loads(ch.chunk_metadata)
                    except json.JSONDecodeError:
                        pass
                header = meta.get("header", "")
                node_type = meta.get("node_type", "text")
                lines.append(
                    f"--- Chunk {ch.chunk_index} [{node_type}] ({ch.token_count} tokens) ---"
                )
                if header:
                    lines.append(f"  Header: {header}")
                lines.append(ch.content[:2000])
                lines.append("")
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="download_document_structure",
        description="Export the heading skeleton of a document as markdown.",
    )
    def download_document_structure(job_id: str) -> str:
        db = _get_db()
        try:
            doc = _doc_repo.find_document_by_job_id(db, job_id)
            if not doc:
                return f"Document not found: {job_id}"
            if doc.status != "completed":
                return f"Document not ready. Status: {doc.status}"

            structure = (
                db.query(OrmDocumentStructure)
                .filter(OrmDocumentStructure.document_id == doc.id)
                .first()
            )
            if not structure or not structure.skeleton_structure:
                return "No structure available."

            return (
                f"# Structure: {doc.filename}\n"
                f"# job_id: {doc.job_id}\n\n"
                f"{structure.skeleton_structure}"
            )
        finally:
            db.close()

    @mcp.tool(
        name="list_upload_jobs",
        description="List recent upload jobs with status, progress, and timing.",
    )
    def list_upload_jobs(limit: int = 20) -> str:
        from kapsula.presentation.upload.upload_job_manager import UploadJobManager

        manager = UploadJobManager()
        jobs = manager.list_recent(limit)
        if not jobs:
            return "No upload jobs found."

        lines = [f"Upload jobs ({len(jobs)}):\n"]
        for job in jobs:
            duration = f"{job['duration']:.1f}s" if job.get("duration") else "—"
            lines.append(
                f"  • {job['filename']} [{job['status']}] "
                f"{job.get('progress', '?')}% "
                f"stage={job.get('stage', '?')} "
                f"chunks={job.get('chunk_count', '—')} "
                f"duration={duration} "
                f"ingestion={job.get('ingestion_mode', '?')}\n"
                f"    job_id: {job['job_id']} "
                f"collection: {job.get('collection_name', '—')}"
            )
            if job.get("error"):
                lines.append(f"    error: {job['error'][:200]}")
        return "\n".join(lines)

    @mcp.tool(
        name="get_upload_job",
        description="Get detailed information about a specific upload job.",
    )
    def get_upload_job(job_id: str) -> str:
        from kapsula.presentation.upload.upload_job_manager import UploadJobManager

        manager = UploadJobManager()
        job = manager.get(job_id)
        if not job:
            return f"Upload job not found: {job_id}"

        lines = [
            f"Upload Job: {job['filename']}",
            f"  job_id: {job['job_id']}",
            f"  Status: {job['status']}",
            f"  Progress: {job.get('progress', '?')}%",
            f"  Stage: {job.get('stage', '?')}",
            f"  Message: {job.get('message', '')}",
            f"  Collection: {job.get('collection_name', '—')}",
            f"  Ingestion mode: {job.get('ingestion_mode', '?')}",
            f"  Chunks: {job.get('chunk_count', '—')}",
            f"  Sub-documents: {job.get('subdocument_count', '—')}",
            f"  Duration: {job.get('duration') or '—'}",
            f"  Created: {job.get('created_at', '?')}",
            f"  Updated: {job.get('updated_at', '?')}",
        ]
        if job.get("error"):
            lines.append(f"  Error: {job['error']}")
        return "\n".join(lines)

    @mcp.tool(
        name="get_upload_metrics",
        description="Aggregate upload metrics: counts by status, durations, and per-ingestion-mode breakdown.",
    )
    def get_upload_metrics() -> str:
        db = _get_db()
        try:
            from kapsula.infrastructure.data import UploadJob as OrmUploadJob
            from sqlalchemy import func

            total = db.query(OrmUploadJob).count()
            if total == 0:
                return "No upload jobs recorded yet."

            completed = (
                db.query(OrmUploadJob)
                .filter(OrmUploadJob.status == "completed")
                .count()
            )
            failed = (
                db.query(OrmUploadJob).filter(OrmUploadJob.status == "failed").count()
            )
            processing = (
                db.query(OrmUploadJob)
                .filter(OrmUploadJob.status == "processing")
                .count()
            )

            durations = [
                row[0]
                for row in db.query(OrmUploadJob.duration)
                .filter(OrmUploadJob.duration.isnot(None))
                .all()
                if row[0] is not None
            ]
            avg_duration = sum(durations) / len(durations) if durations else None
            max_duration = max(durations) if durations else None
            total_chunks = (
                db.query(func.sum(OrmUploadJob.chunk_count))
                .filter(OrmUploadJob.chunk_count.isnot(None))
                .scalar()
                or 0
            )

            mode_stats = (
                db.query(
                    OrmUploadJob.ingestion_mode,
                    func.count(OrmUploadJob.id),
                    func.avg(OrmUploadJob.duration),
                )
                .filter(OrmUploadJob.ingestion_mode.isnot(None))
                .group_by(OrmUploadJob.ingestion_mode)
                .all()
            )

            lines = [
                "Upload Metrics",
                f"  Total jobs: {total}",
                f"  Completed: {completed}",
                f"  Failed: {failed}",
                f"  Processing: {processing}",
                f"  Total chunks indexed: {total_chunks}",
            ]
            if avg_duration is not None:
                lines.append(f"  Average duration: {avg_duration:.1f}s")
            if max_duration is not None:
                lines.append(f"  Max duration: {max_duration:.1f}s")
            if mode_stats:
                lines.append("\n  By ingestion mode:")
                for mode, count, avg_dur in mode_stats:
                    dur = f"{avg_dur:.1f}s" if avg_dur else "—"
                    lines.append(f"    {mode}: {count} jobs, avg {dur}")
            return "\n".join(lines)
        finally:
            db.close()
