"""Collection management routes."""

import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, File, UploadFile, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from kapsula.infrastructure.data import get_db, DATA_DIR
from kapsula.infrastructure.data.tables.collection import Collection as OrmCollection
from kapsula.infrastructure.data.tables.account import Account as OrmAccount
from kapsula.infrastructure.repositories.data.sql_collection_repository import (
    SqlCollectionRepository,
)
from kapsula.core.domain.entities.collection import Collection
from kapsula.infrastructure.logging_config import get_logger
from ..models import CollectionResponse, CollectionListResponse

logger = get_logger(__name__)
router = APIRouter()

# Create logos directory
LOGOS_DIR = os.path.join(DATA_DIR, "logos")
os.makedirs(LOGOS_DIR, exist_ok=True)

# Allowed image extensions
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def save_logo(file: UploadFile, collection_id: str) -> str:
    """Save logo file and return filename."""
    # Validate file extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Generate unique filename
    logo_filename = f"{collection_id}{file_ext}"
    logo_path = os.path.join(LOGOS_DIR, logo_filename)

    # Save file
    with open(logo_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    logger.info(f"Logo saved: {logo_filename}")
    return logo_filename


_collection_repo = SqlCollectionRepository()
@router.post("/", response_model=CollectionResponse)
async def create_collection(
    request: Request,
    name: str = Form(...),
    account_id: str = Form(None),
    logo: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """
    Create a new collection with optional logo.

    - **name**: Name of the collection
    - **account_id**: (Optional) Account ID to link collection to
    - **logo**: (Optional) Logo image file (PNG, JPG, GIF, SVG, WebP)

    Returns collection ID (GUID) and metadata.
    """
    logger.info(f"Creating collection: {name}")

    # Get client IP
    client_ip = request.client.host

    # Generate unique collection ID (GUID)
    collection_id = str(uuid.uuid4())
    logger.info(f"Generated collection ID: {collection_id}")

    # If account_id provided, verify it exists and get the account
    account = None
    if account_id:
        account = db.query(OrmAccount).filter(OrmOrmAccount.account_id == account_id).first()
        if not account:
            logger.warning(f"Account not found: {account_id}")
            raise HTTPException(
                status_code=404, detail=f"Account not found: {account_id}"
            )
        logger.info(f"Linking collection to account: {account.account_id}")

    # Save logo if provided
    logo_filename = None
    if logo:
        try:
            logo_filename = save_logo(logo, collection_id)
        except Exception as e:
            logger.error(f"Error saving logo: {e}")
            raise HTTPException(status_code=500, detail=f"Error saving logo: {str(e)}")

    # Create collection via repository
    collection = Collection(
        collection_id=collection_id,
        name=name,
        logo_filename=logo_filename,
        account_id=account.id if account else None,
        ip_address=client_ip,
    )
    _collection_repo.save(db, collection)

    logger.info(f"Collection created: {collection_id}")

    return CollectionResponse(
        collection_id=collection.collection_id,
        name=collection.name,
        logo_url=(
            f"/api/v1/collections/{collection_id}/logo/download"
            if logo_filename
            else None
        ),
        created_at=collection.created_at.isoformat(),
        document_count=0,
    )


@router.put("/{collection_id}/logo", response_model=CollectionResponse)
async def upload_collection_logo(
    collection_id: str,
    request: Request,
    logo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload or update collection logo.

    - **collection_id**: Collection ID (GUID)
    - **logo**: Logo image file (PNG, JPG, GIF, SVG, WebP)

    Returns updated collection information.
    """
    logger.info(f"Uploading logo for collection: {collection_id}")

    # Get collection
    collection = (
        db.query(OrmCollection).filter(OrmOrmCollection.collection_id == collection_id).first()
    )
    if not collection:
        logger.warning(f"Collection not found: {collection_id}")
        raise HTTPException(status_code=404, detail="Collection not found")

    # Delete old logo if exists
    if collection.logo_filename:
        old_logo_path = os.path.join(LOGOS_DIR, collection.logo_filename)
        if os.path.exists(old_logo_path):
            os.remove(old_logo_path)
            logger.info(f"Deleted old logo: {collection.logo_filename}")

    # Save new logo
    try:
        logo_filename = save_logo(logo, collection_id)
        collection.logo_filename = logo_filename
        db.commit()
        db.refresh(collection)
        logger.info(f"Logo updated for collection: {collection_id}")
    except Exception as e:
        logger.error(f"Error saving logo: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving logo: {str(e)}")

    return CollectionResponse(
        collection_id=collection.collection_id,
        name=collection.name,
        logo_url=(
            f"/api/v1/collections/{collection_id}/logo/download"
            if logo_filename
            else None
        ),
        created_at=collection.created_at.isoformat(),
        document_count=len(collection.documents),
    )


@router.get("/{collection_id}/logo/download")
async def download_collection_logo(collection_id: str, db: Session = Depends(get_db)):
    """
    Download the logo for a specific collection.

    - **collection_id**: Collection ID (GUID)

    Returns the logo file as a download attachment.
    """
    logger.debug(f"Downloading logo for collection: {collection_id}")

    # Get collection
    collection = (
        db.query(OrmCollection).filter(OrmOrmCollection.collection_id == collection_id).first()
    )
    if not collection:
        logger.warning(f"Collection not found: {collection_id}")
        raise HTTPException(status_code=404, detail="Collection not found")

    if not collection.logo_filename:
        raise HTTPException(status_code=404, detail="Collection has no logo")

    logo_path = os.path.join(LOGOS_DIR, collection.logo_filename)
    if not os.path.exists(logo_path):
        logger.warning(f"Logo file not found: {collection.logo_filename}")
        raise HTTPException(status_code=404, detail="Logo file not found")

    # Determine media type based on extension
    ext = Path(collection.logo_filename).suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    # Return as downloadable attachment
    return FileResponse(
        logo_path,
        media_type=media_type,
        filename=f"{collection.name}_logo{ext}",
        headers={
            "Content-Disposition": f'attachment; filename="{collection.name}_logo{ext}"'
        },
    )


@router.get("/", response_model=CollectionListResponse)
async def list_collections(request: Request, db: Session = Depends(get_db)):
    """
    List all collections.

    Returns a list of all collections with document counts and logo download URLs.
    """
    logger.debug("Listing all collections")
    collections = db.query(OrmCollection).order_by(OrmCollection.created_at.desc()).all()

    return CollectionListResponse(
        collections=[
            CollectionResponse(
                collection_id=col.collection_id,
                name=col.name,
                logo_url=(
                    f"/api/v1/collections/{col.collection_id}/logo/download"
                    if col.logo_filename
                    else None
                ),
                created_at=col.created_at.isoformat(),
                document_count=len(col.documents),
            )
            for col in collections
        ],
        total=len(collections),
    )


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: str, request: Request, db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific collection.

    - **collection_id**: Collection ID (GUID)

    Returns collection details including document count and logo download URL.
    """
    logger.debug(f"Getting details for collection: {collection_id}")

    collection = (
        db.query(OrmCollection).filter(OrmOrmCollection.collection_id == collection_id).first()
    )
    if not collection:
        logger.warning(f"Collection not found: {collection_id}")
        raise HTTPException(status_code=404, detail="Collection not found")

    return CollectionResponse(
        collection_id=collection.collection_id,
        name=collection.name,
        logo_url=(
            f"/api/v1/collections/{collection_id}/logo/download"
            if collection.logo_filename
            else None
        ),
        created_at=collection.created_at.isoformat(),
        document_count=len(collection.documents),
    )


@router.get("/{collection_id}/documents")
async def list_collection_documents(collection_id: str, db: Session = Depends(get_db)):
    """
    List all documents in a collection.

    - **collection_id**: Collection ID (GUID)

    Returns all documents belonging to this collection.
    """
    logger.debug(f"Listing documents for collection: {collection_id}")

    collection = (
        db.query(OrmCollection).filter(OrmOrmCollection.collection_id == collection_id).first()
    )
    if not collection:
        logger.warning(f"Collection not found: {collection_id}")
        raise HTTPException(status_code=404, detail="Collection not found")

    from ..models import DocumentListResponse, DocumentListItem

    return DocumentListResponse(
        documents=[
            DocumentListItem(
                id=doc.id,
                job_id=doc.job_id,
                collection_id=collection.collection_id,
                collection_name=collection.name,
                filename=doc.filename,
                size=doc.size,
                status=doc.status,
                created_at=doc.created_at.isoformat(),
                duration=doc.duration,
                chunk_count=len(doc.chunks),
            )
            for doc in collection.documents
        ],
        total=len(collection.documents),
    )


@router.get("/{collection_id}/export")
async def export_collection_data(
    collection_id: str, request: Request, db: Session = Depends(get_db)
):
    """
    Export complete collection data including all documents and library cards.

    - **collection_id**: Collection ID (GUID)

    Returns comprehensive collection information with:
    - All documents (excluding original markdown content)
    - All library cards (document-level and collection-level, excluding extra_metadata)
    - Complete metadata including logo download URL

    This endpoint is useful for backup, migration, or comprehensive data analysis.
    """
    from kapsula.infrastructure.data import LibraryCard
    from ..models import CollectionExportInfo, DocumentExportInfo, LibraryCardInfo

    logger.info(f"Exporting complete data for collection: {collection_id}")

    # Get collection
    collection = (
        db.query(OrmCollection).filter(OrmOrmCollection.collection_id == collection_id).first()
    )
    if not collection:
        logger.warning(f"Collection not found: {collection_id}")
        raise HTTPException(status_code=404, detail="Collection not found")

    documents_data = []
    total_library_cards = 0

    # Process each document in collection
    for document in collection.documents:
        # Get document-level library cards
        doc_library_cards = (
            db.query(LibraryCard)
            .filter(
                LibraryCard.document_id == document.id,
                LibraryCard.collection_id.is_(None),  # Document-level only
            )
            .all()
        )

        doc_library_cards_info = [
            LibraryCardInfo(
                id=card.id,
                level=card.level,
                title=card.title,
                content=card.content,
                created_at=card.created_at.isoformat(),
            )
            for card in doc_library_cards
        ]

        documents_data.append(
            DocumentExportInfo(
                id=document.id,
                job_id=document.job_id,
                filename=document.filename,
                size=document.size,
                status=document.status,
                created_at=document.created_at.isoformat(),
                duration=document.duration,
                chunk_count=len(document.chunks),
                library_cards=doc_library_cards_info,
            )
        )

        total_library_cards += len(doc_library_cards_info)

    # Get collection-level library cards
    collection_library_cards = (
        db.query(LibraryCard)
        .filter(
            LibraryCard.collection_id == collection.id,
            LibraryCard.document_id.is_(None),  # Collection-level only
        )
        .all()
    )

    collection_library_cards_info = [
        LibraryCardInfo(
            id=card.id,
            level=card.level,
            title=card.title,
            content=card.content,
            created_at=card.created_at.isoformat(),
        )
        for card in collection_library_cards
    ]

    total_library_cards += len(collection_library_cards_info)

    logger.info(
        f"Collection export completed: {len(documents_data)} documents, "
        f"{total_library_cards} library cards"
    )

    return CollectionExportInfo(
        collection_id=collection.collection_id,
        name=collection.name,
        logo_url=(
            f"/api/v1/collections/{collection_id}/logo/download"
            if collection.logo_filename
            else None
        ),
        created_at=collection.created_at.isoformat(),
        document_count=len(collection.documents),
        documents=documents_data,
        library_cards=collection_library_cards_info,
    )
