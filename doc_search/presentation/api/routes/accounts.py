"""Account management routes."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from doc_search.infrastructure.data import get_db, Account, LibraryCard
from doc_search.infrastructure.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()


# Pydantic models for request/response
from pydantic import BaseModel

class AccountCreate(BaseModel):
    name: str

class AccountResponse(BaseModel):
    account_id: str
    name: str
    created_at: str
    collection_count: int

class AccountListResponse(BaseModel):
    accounts: List[AccountResponse]
    total: int


@router.post("/", response_model=AccountResponse)
async def create_account(
    request: Request,
    account_data: AccountCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new account.

    - **name**: Name of the account

    Returns account ID (GUID) and metadata.
    """
    logger.info(f"Creating account: {account_data.name}")

    # Get client IP
    client_ip = request.client.host

    # Generate unique account ID (GUID)
    account_id = str(uuid.uuid4())
    logger.info(f"Generated account ID: {account_id}")

    # Create account record
    account = Account(
        account_id=account_id,
        name=account_data.name,
        ip_address=client_ip
    )

    db.add(account)
    db.commit()
    db.refresh(account)

    logger.info(f"Account created: {account_id}")

    return AccountResponse(
        account_id=account.account_id,
        name=account.name,
        created_at=account.created_at.isoformat(),
        collection_count=0
    )


@router.get("/", response_model=AccountListResponse)
async def list_accounts(db: Session = Depends(get_db)):
    """
    List all accounts.

    Returns a list of all accounts with collection counts.
    """
    logger.debug("Listing all accounts")
    accounts = db.query(Account).order_by(Account.created_at.desc()).all()

    return AccountListResponse(
        accounts=[
            AccountResponse(
                account_id=acc.account_id,
                name=acc.name,
                created_at=acc.created_at.isoformat(),
                collection_count=len(acc.collections)
            )
            for acc in accounts
        ],
        total=len(accounts)
    )


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(account_id: str, db: Session = Depends(get_db)):
    """
    Get detailed information about a specific account.

    - **account_id**: Account ID (GUID)

    Returns account details including collection count.
    """
    logger.debug(f"Getting details for account: {account_id}")

    account = db.query(Account).filter(Account.account_id == account_id).first()
    if not account:
        logger.warning(f"Account not found: {account_id}")
        raise HTTPException(status_code=404, detail="Account not found")

    return AccountResponse(
        account_id=account.account_id,
        name=account.name,
        created_at=account.created_at.isoformat(),
        collection_count=len(account.collections)
    )


from ..models import CollectionListResponse  # ensure available for OpenAPI schema


@router.get("/{account_id}/collections", response_model=CollectionListResponse)
async def list_account_collections(account_id: str, db: Session = Depends(get_db)):
    """
    List all collections in an account.

    - **account_id**: Account ID (GUID)

    Returns all collections belonging to this account.
    """
    logger.debug(f"Listing collections for account: {account_id}")

    account = db.query(Account).filter(Account.account_id == account_id).first()
    if not account:
        logger.warning(f"Account not found: {account_id}")
        raise HTTPException(status_code=404, detail="Account not found")

    from ..models import CollectionResponse, CollectionListResponse

    # Build response including summarized collection-level library card (if available)
    collections_with_summary = []
    for col in account.collections:
        # Get the most recent collection-level library card (not document-level)
        collection_card = (
            db.query(LibraryCard)
            .filter(
                LibraryCard.collection_id == col.id,
                LibraryCard.document_id == None,  # ensure collection-level
            )
            .order_by(LibraryCard.created_at.desc())
            .first()
        )

        collections_with_summary.append(
            CollectionResponse(
                collection_id=col.collection_id,
                name=col.name,
                created_at=col.created_at.isoformat(),
                document_count=len(col.documents),
                library_card_summary=(collection_card.content if collection_card else None),
            )
        )

    return CollectionListResponse(
        collections=collections_with_summary,
        total=len(account.collections)
    )


from ..models import AccountExportResponse  # ensure available for OpenAPI schema


@router.get("/{account_id}/export", response_model=AccountExportResponse)
async def export_account_data(account_id: str, db: Session = Depends(get_db)):
    """
    Export complete account data including all collections, documents, file content, and library cards.

    - **account_id**: Account ID (GUID)

    Returns comprehensive account information with:
    - All collections
    - All documents with original file content
    - All library cards (document-level and collection-level)
    - Complete metadata

    This endpoint is useful for backup, migration, or comprehensive data analysis.
    """
    logger.info(f"Exporting complete data for account: {account_id}")

    # Get account
    account = db.query(Account).filter(Account.account_id == account_id).first()
    if not account:
        logger.warning(f"Account not found: {account_id}")
        raise HTTPException(status_code=404, detail="Account not found")

    from ..models import (
        AccountExportResponse,
        CollectionExportInfo,
        DocumentExportInfo,
        LibraryCardInfo
    )

    collections_data = []
    total_documents = 0
    total_library_cards = 0

    # Process each collection
    for collection in account.collections:
        documents_data = []

        # Process each document in collection
        for document in collection.documents:
            # Get document-level library cards
            doc_library_cards = db.query(LibraryCard).filter(
                LibraryCard.document_id == document.id,
                LibraryCard.collection_id == None  # Document-level only
            ).all()

            doc_library_cards_info = [
                LibraryCardInfo(
                    id=card.id,
                    level=card.level,
                    title=card.title,
                    content=card.content,
                    created_at=card.created_at.isoformat()
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
                    library_cards=doc_library_cards_info
                )
            )

            total_documents += 1
            total_library_cards += len(doc_library_cards_info)

        # Get collection-level library cards
        collection_library_cards = db.query(LibraryCard).filter(
            LibraryCard.collection_id == collection.id,
            LibraryCard.document_id == None  # Collection-level only
        ).all()

        collection_library_cards_info = [
            LibraryCardInfo(
                id=card.id,
                level=card.level,
                title=card.title,
                content=card.content,
                created_at=card.created_at.isoformat()
            )
            for card in collection_library_cards
        ]

        total_library_cards += len(collection_library_cards_info)

        collections_data.append(
            CollectionExportInfo(
                collection_id=collection.collection_id,
                name=collection.name,
                created_at=collection.created_at.isoformat(),
                document_count=len(collection.documents),
                documents=documents_data,
                library_cards=collection_library_cards_info
            )
        )

    logger.info(
        f"Account export completed: {len(collections_data)} collections, "
        f"{total_documents} documents, {total_library_cards} library cards"
    )

    return AccountExportResponse(
        account_id=account.account_id,
        name=account.name,
        created_at=account.created_at.isoformat(),
        collection_count=len(account.collections),
        total_documents=total_documents,
        total_library_cards=total_library_cards,
        collections=collections_data
    )
