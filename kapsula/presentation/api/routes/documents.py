"""Document processing routes."""

import json

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import Response
from sqlalchemy.orm import Session

from kapsula.infrastructure.data import (
    SessionLocal,
    get_db,
)
from kapsula.infrastructure.data.tables.chunk import Chunk as OrmChunk
from kapsula.infrastructure.data.tables.document import Document as OrmDocument
from kapsula.infrastructure.data.tables.document_structure import (
    DocumentStructure as OrmDocumentStructure,
)
from kapsula.infrastructure.logging_config import get_logger
from kapsula.presentation.upload.stale_progress_guard import StaleProgressGuard

from ..models import (
    DocumentDetailResponse,
    DocumentListItem,
    DocumentListResponse,
    ProgressResponse,
    UploadResponse,
)
from ..tasks import (
    get_processing_status,
    process_document_with_subdocuments,
)

logger = get_logger(__name__)
router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    collection_id: str,
    file: UploadFile = File(...),
    max_tokens: int = 512,
    ingestion_mode: str = "indexed",
    db: Session = Depends(get_db),
):
    """
    Upload a markdown file to a collection for processing.

    Use well-structured markdown with H2/H3 headings — each heading becomes
    a library card for navigation and context expansion. Without proper headings,
    the browse-before-search workflow breaks down.

    - **collection_id**: Collection ID (GUID) to upload document to
    - **file**: Markdown (.md) file — must use H2/H3 headings for best results
    - **max_tokens**: Maximum token length per chunk (default: 512)
    - **ingestion_mode**: \"fast\" (no indexes), \"indexed\" (FAISS+BM25, default), \"full\" (indexes + summary)

    Returns job ID for tracking progress via GET /documents/progress/{job_id}.
    """
    content = await file.read()

    from kapsula.startup import create_upload_document_use_case

    use_case = create_upload_document_use_case()

    try:
        result = use_case.execute_from_content(
            db=db,
            content_bytes=content,
            filename=file.filename or "upload.md",
            collection_id=collection_id,
            max_tokens=max_tokens,
            ingestion_mode=ingestion_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Background processing (FastAPI-specific, stays in route)
    background_tasks.add_task(
        process_document_with_subdocuments,
        job_id=result.job_id,
        markdown_content=content.decode("utf-8"),
        max_tokens=max_tokens,
        db=SessionLocal(),
        ingestion_mode=result.ingestion_mode,
    )

    logger.info(
        "Upload started: job_id=%s filename=%s collection=%s mode=%s",
        result.job_id,
        result.filename,
        result.collection_name,
        result.ingestion_mode,
    )

    return UploadResponse(
        job_id=result.job_id,
        collection_id=collection_id,
        status="processing",
        message=f"Document uploaded successfully. Processing started with ingestion_mode={result.ingestion_mode}.",
        ingestion_mode=result.ingestion_mode,
    )


@router.get("/progress/{job_id}", response_model=ProgressResponse)
async def get_progress(job_id: str, db: Session = Depends(get_db)):
    """
    Get processing progress for a job.

    - **job_id**: Job ID (GUID) to check

    Returns current processing status and progress percentage.
    """
    logger.debug(f"Progress check for job: {job_id}")

    # Check if document exists
    document = db.query(OrmDocument).filter(OrmDocument.job_id == job_id).first()
    if not document:
        logger.warning(f"Job not found: {job_id}")
        raise HTTPException(status_code=404, detail="Job not found")

    # Get progress from in-memory status. If the database already reached a
    # terminal state, never let stale in-memory progress look stuck forever.
    status = get_processing_status(job_id)
    if status:
        live_progress = int(status.get("progress", 0) or 0)
        live_status = status.get("status")
        live_stage = status.get("stage")
        terminal_override = StaleProgressGuard.terminal_override(
            document_status=document.status,
            live_status=live_status,
            live_stage=live_stage,
            live_progress=live_progress,
            chunk_count=len(document.chunks),
            duration=document.duration,
        )
        if terminal_override:
            return ProgressResponse(**terminal_override)
        return ProgressResponse(**status)

    # If not in memory, return database status
    logger.debug(f"Job {job_id} not in memory, returning DB status: {document.status}")
    return ProgressResponse(
        status=document.status,
        progress=100 if document.status == "completed" else 0,
        stage=document.status,
        message=f"Document status: {document.status}",
    )


@router.get("/download/{job_id}/structure")
async def download_structure(job_id: str, db: Session = Depends(get_db)):
    """
    Download document structure as markdown file.

    - **job_id**: Job ID (GUID) of the document

    Returns .md file with skeleton structure.
    """
    from fastapi.responses import Response

    logger.info(f"Structure download request for job: {job_id}")

    # Check if document exists and is completed
    document = db.query(OrmDocument).filter(OrmDocument.job_id == job_id).first()
    if not document:
        logger.warning(f"Job not found: {job_id}")
        raise HTTPException(status_code=404, detail="Job not found")

    if document.status != "completed":
        logger.warning(f"Job {job_id} not completed, status: {document.status}")
        raise HTTPException(
            status_code=400,
            detail=f"Document processing not completed. Current status: {document.status}",
        )

    # Get document structure
    structure = (
        db.query(OrmDocumentStructure)
        .filter(OrmDocumentStructure.document_id == document.id)
        .first()
    )

    if not structure or not structure.skeleton_structure:
        logger.warning(f"Job {job_id} has no structure")
        raise HTTPException(status_code=404, detail="Document structure not found")

    logger.info(f"Job {job_id}: Returning structure as MD file")

    # Return as downloadable markdown file
    filename = document.filename.replace(".md", "_structure.md")
    return Response(
        content=structure.skeleton_structure,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/download/{job_id}/chunks")
async def download_chunks(job_id: str, db: Session = Depends(get_db)):
    """
    Download chunked content as JSON file.

    - **job_id**: Job ID (GUID) of the document

    Returns JSON file with all chunks and metadata.
    """
    logger.info(f"Chunks download request for job: {job_id}")

    # Check if document exists and is completed
    document = db.query(OrmDocument).filter(OrmDocument.job_id == job_id).first()
    if not document:
        logger.warning(f"Job not found: {job_id}")
        raise HTTPException(status_code=404, detail="Job not found")

    if document.status != "completed":
        logger.warning(f"Job {job_id} not completed, status: {document.status}")
        raise HTTPException(
            status_code=400,
            detail=f"Document processing not completed. Current status: {document.status}",
        )

    # Get all chunks
    chunks = (
        db.query(OrmChunk)
        .filter(OrmChunk.document_id == document.id)
        .order_by(OrmChunk.chunk_index)
        .all()
    )

    logger.info(f"Job {job_id}: Preparing download with {len(chunks)} chunks")

    # Prepare response data
    response_data = {
        "document": {
            "id": document.id,
            "job_id": document.job_id,
            "filename": document.filename,
            "size": document.size,
            "created_at": document.created_at.isoformat(),
            "duration": document.duration,
            "ip_address": document.ip_address,
        },
        "chunks": [
            {
                "id": chunk.id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "token_count": chunk.token_count,
                "metadata": (
                    json.loads(chunk.chunk_metadata) if chunk.chunk_metadata else {}
                ),
            }
            for chunk in chunks
        ],
        "total_chunks": len(chunks),
    }

    # Return as downloadable JSON file
    filename = document.filename.replace(".md", "_chunks.json")
    return Response(
        content=json.dumps(response_data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/list", response_model=DocumentListResponse)
async def list_documents(db: Session = Depends(get_db)):
    """
    List all uploaded documents with their status.

    Returns a list of all documents in the database.
    """
    logger.debug("Listing all documents")
    documents = db.query(OrmDocument).order_by(OrmDocument.created_at.desc()).all()

    return DocumentListResponse(
        documents=[
            DocumentListItem(
                id=doc.id,
                job_id=doc.job_id,
                collection_id=doc.collection.collection_id,
                collection_name=doc.collection.name,
                filename=doc.filename,
                size=doc.size,
                status=doc.status,
                created_at=doc.created_at.isoformat(),
                duration=doc.duration,
                chunk_count=len(doc.chunks),
            )
            for doc in documents
        ],
        total=len(documents),
    )


@router.get("/{job_id}", response_model=DocumentDetailResponse)
async def get_document(job_id: str, db: Session = Depends(get_db)):
    """
    Get detailed information about a specific document.

    - **job_id**: Job ID (GUID) of the document

    Returns document details including structure and chunk information.
    """
    logger.debug(f"Getting details for job: {job_id}")

    document = db.query(OrmDocument).filter(OrmDocument.job_id == job_id).first()
    if not document:
        logger.warning(f"Job not found: {job_id}")
        raise HTTPException(status_code=404, detail="Job not found")

    structure = (
        db.query(OrmDocumentStructure)
        .filter(OrmDocumentStructure.document_id == document.id)
        .first()
    )

    return DocumentDetailResponse(
        id=document.id,
        job_id=document.job_id,
        collection_id=document.collection.collection_id,
        collection_name=document.collection.name,
        filename=document.filename,
        size=document.size,
        status=document.status,
        created_at=document.created_at.isoformat(),
        duration=document.duration,
        ip_address=document.ip_address,
        chunk_count=len(document.chunks),
        structure=structure.skeleton_structure if structure else None,
    )


@router.delete("/{job_id}")
async def delete_document(job_id: str, db: Session = Depends(get_db)):
    """
    Soft-delete a document: archives it and removes chunks from search indexes.

    - **job_id**: Job ID (GUID) of the document to delete

    The document is marked as archived (soft delete). Its chunks are removed
    from the database, document-level index files are deleted, and aggregate
    indexes are rebuilt to reflect the removal.
    """
    from kapsula.startup import create_delete_document_use_case

    try:
        use_case = create_delete_document_use_case()
        result = use_case.execute(db, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "job_id": result.job_id,
        "filename": result.filename,
        "status": "archived",
        "chunks_deleted": result.chunks_deleted,
        "rebuild": result.rebuild_lines,
    }
