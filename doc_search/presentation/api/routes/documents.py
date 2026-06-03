"""Document processing routes."""

import json
import uuid

from fastapi import (
    APIRouter,
    File,
    UploadFile,
    Depends,
    HTTPException,
    Request,
    BackgroundTasks,
)
from fastapi.responses import Response
from sqlalchemy.orm import Session

from doc_search.infrastructure.data import (
    get_db,
    SessionLocal,
    Document,
    DocumentStructure,
    Chunk,
    Collection,
)
from doc_search.infrastructure.logging_config import get_logger
from ..models import (
    UploadResponse,
    ProgressResponse,
    DocumentListResponse,
    DocumentDetailResponse,
    DocumentListItem,
)
from doc_search.core.application.dto.upload_ingestion_mode import UploadIngestionMode
from doc_search.presentation.upload.stale_progress_guard import StaleProgressGuard
from doc_search.presentation.upload.upload_job_manager import UploadJobManager
from ..tasks import (
    process_document_with_subdocuments,
    get_processing_status,
    processing_status,
)

logger = get_logger(__name__)
router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    request: Request,
    collection_id: str,
    file: UploadFile = File(...),
    max_tokens: int = 512,
    ingestion_mode: str = "indexed",
    db: Session = Depends(get_db),
):
    """
    Upload a markdown file for processing to a collection.

    - **collection_id**: Collection ID (GUID) to upload document to
    - **file**: Markdown file to upload
    - **max_tokens**: Maximum token length for embedding model (default: 512)
    - **ingestion_mode**: Upload intent: fast, indexed (default), or full

    Returns job ID and processing status.
    """
    try:
        ingestion_mode = UploadIngestionMode.normalize(ingestion_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Received upload request: collection_id=%s, filename=%s, max_tokens=%s, ingestion_mode=%s",
        collection_id,
        file.filename,
        max_tokens,
        ingestion_mode,
    )

    # Verify collection exists
    collection = (
        db.query(Collection).filter(Collection.collection_id == collection_id).first()
    )
    if not collection:
        logger.warning(f"Collection not found: {collection_id}")
        raise HTTPException(status_code=404, detail="Collection not found")

    # Validate file type
    if not file.filename.endswith(".md"):
        logger.warning(f"Invalid file type rejected: {file.filename}")
        raise HTTPException(
            status_code=400, detail="Only markdown (.md) files are allowed"
        )

    # Read file content
    content = await file.read()
    markdown_content = content.decode("utf-8")
    logger.debug(f"File content read: {len(content)} bytes")

    # Get client IP
    client_ip = request.client.host
    logger.debug(f"Client IP: {client_ip}")

    # Generate unique job ID (GUID)
    job_id = str(uuid.uuid4())
    logger.info(f"Generated job ID: {job_id}")

    # Create document record
    document = Document(
        job_id=job_id,
        collection_id=collection.id,
        filename=file.filename,
        size=len(content),
        ip_address=client_ip,
        content=markdown_content,
        status="processing",
    )

    db.add(document)
    db.commit()
    db.refresh(document)
    logger.info(
        f"Document created with job_id: {job_id}, db_id: {document.id}, collection: {collection.name}"
    )

    # Initialize progress tracking
    processing_status[job_id] = {
        "status": "processing",
        "progress": 0,
        "stage": "queued",
        "message": f"Document queued for {ingestion_mode} ingestion...",
        "ingestion_mode": ingestion_mode,
    }
    UploadJobManager().create(
        job_id,
        filename=file.filename,
        collection_id=collection.id,
        collection_name=collection.name,
        ingestion_mode=ingestion_mode,
    )

    # Process document in background using Russian Doll architecture
    background_tasks.add_task(
        process_document_with_subdocuments,
        job_id=job_id,
        markdown_content=markdown_content,
        max_tokens=max_tokens,
        db=SessionLocal(),
        ingestion_mode=ingestion_mode,
    )

    return UploadResponse(
        job_id=job_id,
        collection_id=collection_id,
        status="processing",
        message=f"Document uploaded successfully. Processing started with ingestion_mode={ingestion_mode}.",
        ingestion_mode=ingestion_mode,
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
    document = db.query(Document).filter(Document.job_id == job_id).first()
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
    document = db.query(Document).filter(Document.job_id == job_id).first()
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
        db.query(DocumentStructure)
        .filter(DocumentStructure.document_id == document.id)
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
    document = db.query(Document).filter(Document.job_id == job_id).first()
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
        db.query(Chunk)
        .filter(Chunk.document_id == document.id)
        .order_by(Chunk.chunk_index)
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
    documents = db.query(Document).order_by(Document.created_at.desc()).all()

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

    document = db.query(Document).filter(Document.job_id == job_id).first()
    if not document:
        logger.warning(f"Job not found: {job_id}")
        raise HTTPException(status_code=404, detail="Job not found")

    structure = (
        db.query(DocumentStructure)
        .filter(DocumentStructure.document_id == document.id)
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
    from doc_search.startup import create_delete_document_use_case

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
