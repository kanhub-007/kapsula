"""Account management routes."""

import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from kapsula.infrastructure.data import get_db
from kapsula.infrastructure.data.tables.account import Account as OrmAccount
from kapsula.infrastructure.data.tables.collection import Collection as OrmCollection
from kapsula.infrastructure.data import LibraryCard as OrmLibraryCard
from kapsula.infrastructure.repositories.data.sql_account_repository import (
    SqlAccountRepository,
)
from kapsula.core.domain.entities.account import Account
from kapsula.infrastructure.logging_config import get_logger
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
    client_ip = request.client.host
    account_id = str(uuid.uuid4())
    acc = Account(account_id=account_id, name=account_data.name, ip_address=client_ip)
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
    accounts = _account_repo.list_all(db)
    # Need ORM for collection counts (relationships)
    orm_accounts = {
        a.account_id: db.query(OrmAccount).filter(OrmAccount.account_id == a.account_id).first()
        for a in accounts
    }
    return AccountListResponse(
        accounts=[
            AccountResponse(
                account_id=acc.account_id,
                name=acc.name,
                created_at=acc.created_at.isoformat() if acc.created_at else "",
                collection_count=len(orm_accounts[acc.account_id].collections)
                if acc.account_id in orm_accounts else 0,
            )
            for acc in accounts
        ],
        total=len(accounts),
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
    collections_with_summary = []
    for col in orm_acc.collections:
        card = (
            db.query(OrmLibraryCard)
            .filter(OrmLibraryCard.collection_id == col.id, OrmLibraryCard.document_id.is_(None))
            .order_by(OrmLibraryCard.created_at.desc())
            .first()
        )
        collections_with_summary.append(
            CollResponse(
                collection_id=col.collection_id,
                name=col.name,
                created_at=col.created_at.isoformat(),
                document_count=len(col.documents),
                library_card_summary=card.content if card else None,
            )
        )
    return CollectionListResponse(collections=collections_with_summary, total=len(orm_acc.collections))


@router.get("/{account_id}/export", response_model=AccountExportResponse)
async def export_account_data(account_id: str, db: Session = Depends(get_db)):
    acc = _account_repo.find_by_account_id(db, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    from ..models import AccountExportResponse, CollectionExportInfo, DocumentExportInfo, LibraryCardInfo
    orm_acc = db.query(OrmAccount).filter(OrmAccount.account_id == account_id).first()
    if not orm_acc:
        raise HTTPException(status_code=404, detail="Account not found")
    collections_data = []
    total_docs = 0; total_cards = 0
    for col in orm_acc.collections:
        docs_data = []
        for doc in col.documents:
            doc_cards = db.query(OrmLibraryCard).filter(
                OrmLibraryCard.document_id == doc.id, OrmLibraryCard.collection_id.is_(None)
            ).all()
            docs_data.append(DocumentExportInfo(
                id=doc.id, job_id=doc.job_id, filename=doc.filename, size=doc.size,
                status=doc.status, created_at=doc.created_at.isoformat(),
                duration=doc.duration, chunk_count=len(doc.chunks),
                library_cards=[LibraryCardInfo(id=c.id, level=c.level, title=c.title, content=c.content, created_at=c.created_at.isoformat()) for c in doc_cards],
            ))
            total_docs += 1; total_cards += len(doc_cards)
        col_cards = db.query(OrmLibraryCard).filter(
            OrmLibraryCard.collection_id == col.id, OrmLibraryCard.document_id.is_(None)
        ).all()
        total_cards += len(col_cards)
        collections_data.append(CollectionExportInfo(
            collection_id=col.collection_id, name=col.name, created_at=col.created_at.isoformat(),
            document_count=len(col.documents), documents=docs_data,
            library_cards=[LibraryCardInfo(id=c.id, level=c.level, title=c.title, content=c.content, created_at=c.created_at.isoformat()) for c in col_cards],
        ))
    return AccountExportResponse(
        account_id=acc.account_id, name=acc.name, created_at=acc.created_at.isoformat() if acc.created_at else "",
        collection_count=len(orm_acc.collections), total_documents=total_docs,
        total_library_cards=total_cards, collections=collections_data,
    )
