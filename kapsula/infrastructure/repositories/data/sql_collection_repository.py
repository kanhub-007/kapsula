"""SQLAlchemy-backed CollectionRepository."""

from sqlalchemy.orm import Session

from kapsula.core.domain.entities.collection import Collection as DomainCollection
from kapsula.core.domain.interfaces.collection_repository import (
    CollectionRepository,
)
from kapsula.infrastructure.data import (
    Collection as OrmCollection,
    Account as OrmAccount,
)
from kapsula.infrastructure.repositories.data.mappers import (
    collection_from_orm,
    collection_to_orm,
)


class SqlCollectionRepository(CollectionRepository):
    """Persists collections via SQLAlchemy, mapping through domain entities."""

    def list_all(self, db: Session) -> list[DomainCollection]:
        orm_list = (
            db.query(OrmCollection)
            .order_by(OrmCollection.created_at.desc())
            .all()
        )
        return [collection_from_orm(c) for c in orm_list]

    def list_by_account(
        self, db: Session, account_id: str
    ) -> list[DomainCollection]:
        orm_list = (
            db.query(OrmCollection)
            .join(OrmAccount)
            .filter(OrmAccount.account_id == account_id)
            .order_by(OrmCollection.created_at.desc())
            .all()
        )
        return [collection_from_orm(c) for c in orm_list]

    def find_by_collection_id(
        self, db: Session, collection_id: str
    ) -> DomainCollection | None:
        orm = (
            db.query(OrmCollection)
            .filter(OrmCollection.collection_id == collection_id)
            .first()
        )
        if orm is None:
            return None
        return collection_from_orm(orm)

    def find_by_id(self, db: Session, internal_id: int) -> DomainCollection | None:
        orm = db.query(OrmCollection).filter(OrmCollection.id == internal_id).first()
        if orm is None:
            return None
        return collection_from_orm(orm)

    def save(self, db: Session, collection: DomainCollection) -> None:
        orm_collection = collection_to_orm(collection)
        db.add(orm_collection)
        db.commit()
        db.refresh(orm_collection)
        collection.id = orm_collection.id
