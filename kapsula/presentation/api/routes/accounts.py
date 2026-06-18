"""Account management routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from kapsula.core.domain.entities.account import Account
from kapsula.infrastructure.data import LibraryCard as OrmLibraryCard
from kapsula.infrastructure.data import get_db
from kapsula.infrastructure.data.tables.account import Account as OrmAccount
from kapsula.infrastructure.logging_config import get_logger
from kapsula.infrastructure.repositories.data.sql_account_repository import (
    SqlAccountRepository,
)

from .._http import client_ip
from ..models import (
    AccountCreate,
    AccountExportResponse,
    AccountListResponse,
    AccountResponse,
    CollectionListResponse,
)

logger = get_logger(__name__)
router = APIRouter()
_account_repo = SqlAccountRepository()


@router.post("/", response_model=AccountResponse)
async def create_account(
    request: Request, account_data: AccountCreate, db: Session = Depends(get_db)
):
    logger.info(f"Creating account: {account_data.name}")
    client_ip_value = client_ip(request)
    account_id = str(uuid.uuid4())
    acc = Account(
        account_id=account_id, name=account_data.name, ip_address=client_ip_value
    )
    _account_repo.save(db, acc)
    logger.info(f"Account created: {account_id}")
    return AccountResponse(
        account_id=account_id,
        name=account_data.name,
        created_at=acc.created_at.isoformat() if acc.created_at else "",
        collection_count=0,
    )


@router.get("/", response_model=AccountListResponse)
async def list_accounts(db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload

    # Single query with eager-loaded collections (closes S3 N+1: previously
    # re-queried each account by GUID to read .collections).
    orm_accounts = (
        db.query(OrmAccount)
        .options(joinedload(OrmAccount.collections))
        .order_by(OrmAccount.created_at.desc())
        .all()
    )
    return AccountListResponse(
        accounts=[
            AccountResponse(
                account_id=acc.account_id,
                name=acc.name,
                created_at=acc.created_at.isoformat() if acc.created_at else "",
                collection_count=len(acc.collections),
            )
            for acc in orm_accounts
        ],
        total=len(orm_accounts),
    )


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(account_id: str, db: Session = Depends(get_db)):
    acc = _account_repo.find_by_account_id(db, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    orm_acc = db.query(OrmAccount).filter(OrmAccount.account_id == account_id).first()
    return AccountResponse(
        account_id=acc.account_id,
        name=acc.name,
        created_at=acc.created_at.isoformat() if acc.created_at else "",
        collection_count=len(orm_acc.collections) if orm_acc else 0,
    )


@router.get("/{account_id}/collections", response_model=CollectionListResponse)
async def list_account_collections(account_id: str, db: Session = Depends(get_db)):
    acc = _account_repo.find_by_account_id(db, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    from ..models import CollectionResponse as CollResponse

    orm_acc = db.query(OrmAccount).filter(OrmAccount.account_id == account_id).first()
    if not orm_acc:
        return CollectionListResponse(collections=[], total=0)
    collections = list(orm_acc.collections)
    col_ids = [c.id for c in collections]
    # Batch: one query for all collection-level summary cards instead of N.
    summary_cards = (
        db.query(OrmLibraryCard)
        .filter(
            OrmLibraryCard.collection_id.in_(col_ids),
            OrmLibraryCard.document_id.is_(None),
        )
        .order_by(OrmLibraryCard.created_at.desc())
        .all()
    )
    summary_by_col: dict[int, str] = {}
    for card in summary_cards:
        # first (newest) wins per collection due to the order_by above
        summary_by_col.setdefault(card.collection_id, card.content)
    collections_with_summary = [
        CollResponse(
            collection_id=col.collection_id,
            name=col.name,
            created_at=col.created_at.isoformat(),
            document_count=len(col.documents),
            library_card_summary=summary_by_col.get(col.id),
        )
        for col in collections
    ]
    return CollectionListResponse(
        collections=collections_with_summary, total=len(collections)
    )


@router.get("/{account_id}/export", response_model=AccountExportResponse)
async def export_account_data(account_id: str, db: Session = Depends(get_db)):
    acc = _account_repo.find_by_account_id(db, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    from ..models import (
        AccountExportResponse,
        CollectionExportInfo,
        DocumentExportInfo,
        LibraryCardInfo,
    )

    orm_acc = db.query(OrmAccount).filter(OrmAccount.account_id == account_id).first()
    if not orm_acc:
        raise HTTPException(status_code=404, detail="Account not found")
    collections = list(orm_acc.collections)
    col_ids = [c.id for c in collections]
    doc_ids = [d.id for c in collections for d in c.documents]

    # Batch the card queries: two queries instead of (collections + documents).
    col_cards = (
        db.query(OrmLibraryCard)
        .filter(
            OrmLibraryCard.collection_id.in_(col_ids),
            OrmLibraryCard.document_id.is_(None),
        )
        .all()
        if col_ids
        else []
    )
    doc_cards = (
        db.query(OrmLibraryCard)
        .filter(
            OrmLibraryCard.document_id.in_(doc_ids),
            OrmLibraryCard.collection_id.is_(None),
        )
        .all()
        if doc_ids
        else []
    )
    col_cards_by_col: dict[int, list] = {}
    for card in col_cards:
        col_cards_by_col.setdefault(card.collection_id, []).append(card)
    doc_cards_by_doc: dict[int, list] = {}
    for card in doc_cards:
        doc_cards_by_doc.setdefault(card.document_id, []).append(card)

    def _card_info(c) -> LibraryCardInfo:
        return LibraryCardInfo(
            id=c.id,
            level=c.level,
            title=c.title,
            content=c.content,
            created_at=c.created_at.isoformat(),
        )

    collections_data = []
    total_docs = 0
    total_cards = 0
    for col in collections:
        docs_data = []
        for doc in col.documents:
            these_doc_cards = doc_cards_by_doc.get(doc.id, [])
            docs_data.append(
                DocumentExportInfo(
                    id=doc.id,
                    job_id=doc.job_id,
                    filename=doc.filename,
                    size=doc.size,
                    status=doc.status,
                    created_at=doc.created_at.isoformat(),
                    duration=doc.duration,
                    chunk_count=len(doc.chunks),
                    library_cards=[_card_info(c) for c in these_doc_cards],
                )
            )
            total_docs += 1
            total_cards += len(these_doc_cards)
        these_col_cards = col_cards_by_col.get(col.id, [])
        total_cards += len(these_col_cards)
        collections_data.append(
            CollectionExportInfo(
                collection_id=col.collection_id,
                name=col.name,
                created_at=col.created_at.isoformat(),
                document_count=len(col.documents),
                documents=docs_data,
                library_cards=[_card_info(c) for c in these_col_cards],
            )
        )
    return AccountExportResponse(
        account_id=acc.account_id,
        name=acc.name,
        created_at=acc.created_at.isoformat() if acc.created_at else "",
        collection_count=len(orm_acc.collections),
        total_documents=total_docs,
        total_library_cards=total_cards,
        collections=collections_data,
    )
