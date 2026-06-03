"""SQLAlchemy-backed AccountRepository."""

from sqlalchemy.orm import Session

from doc_search.core.domain.entities.account import Account as DomainAccount
from doc_search.core.domain.interfaces.account_repository import AccountRepository
from doc_search.infrastructure.data import Account as OrmAccount
from doc_search.infrastructure.repositories.data.mappers import (
    account_from_orm,
    account_to_orm,
)


class SqlAccountRepository(AccountRepository):
    """Persists accounts via SQLAlchemy, mapping through domain entities."""

    def list_all(self, db: Session) -> list[DomainAccount]:
        orm_list = db.query(OrmAccount).order_by(OrmAccount.created_at.desc()).all()
        return [account_from_orm(a) for a in orm_list]

    def find_by_account_id(self, db: Session, account_id: str) -> DomainAccount | None:
        orm = (
            db.query(OrmAccount)
            .filter(OrmAccount.account_id == account_id)
            .first()
        )
        if orm is None:
            return None
        return account_from_orm(orm)

    def save(self, db: Session, account: DomainAccount) -> None:
        orm_account = account_to_orm(account)
        db.add(orm_account)
        db.commit()
        db.refresh(orm_account)
        account.id = orm_account.id
