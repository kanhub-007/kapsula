"""Mappers between domain entities and ORM models.

Every function converts ONE direction, ONE level deep.
Nested relationships are NOT eagerly mapped to avoid cycles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import MissingGreenlet
from sqlalchemy.orm.exc import DetachedInstanceError

from kapsula.infrastructure.logging_config import get_logger

if TYPE_CHECKING:
    from kapsula.core.domain.entities.account import Account as DomainAccount
    from kapsula.core.domain.entities.chunk import Chunk as DomainChunk
    from kapsula.core.domain.entities.collection import Collection as DomainCollection
    from kapsula.core.domain.entities.document import Document as DomainDocument
    from kapsula.core.domain.entities.sub_document import (
        SubDocument as DomainSubDocument,
    )
    from kapsula.core.domain.read_models.chunk_read import ChunkRead
    from kapsula.core.domain.read_models.collection_read import CollectionRead
    from kapsula.core.domain.read_models.document_read import DocumentRead
    from kapsula.core.domain.read_models.library_card_read import LibraryCardRead
    from kapsula.core.domain.read_models.sub_document_read import SubDocumentRead
    from kapsula.infrastructure.data.tables.account import Account as OrmAccount
    from kapsula.infrastructure.data.tables.chunk import Chunk as OrmChunk
    from kapsula.infrastructure.data.tables.collection import (
        Collection as OrmCollection,
    )
    from kapsula.infrastructure.data.tables.document import Document as OrmDocument
    from kapsula.infrastructure.data.tables.sub_document import (
        SubDocument as OrmSubDocument,
    )

logger = get_logger(__name__)


def document_to_orm(domain: DomainDocument) -> OrmDocument:
    """Convert domain Document to ORM Document for persistence."""
    from kapsula.infrastructure.data.tables.document import Document as OrmDocument

    return OrmDocument(
        id=domain.id,
        job_id=domain.job_id,
        collection_id=domain.collection_id,
        filename=domain.filename,
        size=domain.size,
        created_at=domain.created_at,
        ip_address=domain.ip_address,
        duration=domain.duration,
        content=domain.content,
        status=domain.status,
        doc_state=domain.doc_state,
        faiss_index_path=domain.faiss_index_path,
        bm25_index_path=domain.bm25_index_path,
    )


def document_from_orm(orm: OrmDocument) -> DomainDocument:
    """Convert ORM Document to domain Document (collection populated, no nested docs)."""
    from kapsula.core.domain.entities.document import Document

    collection = None
    try:
        if orm.collection is not None:
            collection = _collection_from_orm_safe(orm.collection)
    except (DetachedInstanceError, MissingGreenlet, AttributeError) as exc:
        logger.debug("Document.collection relationship unavailable: %s", exc)
    return Document(
        id=orm.id,
        job_id=orm.job_id,
        collection_id=orm.collection_id,
        filename=orm.filename,
        size=orm.size,
        created_at=orm.created_at,
        ip_address=orm.ip_address,
        duration=orm.duration,
        content=orm.content,
        status=orm.status,
        doc_state=orm.doc_state,
        faiss_index_path=orm.faiss_index_path,
        bm25_index_path=orm.bm25_index_path,
        collection=collection,
        chunks=[],
        sub_documents=[],
    )


def collection_to_orm(domain: DomainCollection) -> OrmCollection:
    """Convert domain Collection to ORM Collection."""
    from kapsula.infrastructure.data.tables.collection import (
        Collection as OrmCollection,
    )

    return OrmCollection(
        id=domain.id,
        collection_id=domain.collection_id,
        account_id=domain.account_id,
        name=domain.name,
        logo_filename=domain.logo_filename,
        created_at=domain.created_at,
        ip_address=domain.ip_address,
    )


def collection_from_orm(orm: OrmCollection) -> DomainCollection:
    """Convert ORM Collection to domain Collection (account populated, no nested docs)."""
    from kapsula.core.domain.entities.collection import Collection

    account = None
    try:
        if orm.account is not None:
            account = _account_from_orm_safe(orm.account)
    except (DetachedInstanceError, MissingGreenlet, AttributeError) as exc:
        logger.debug("Collection.account relationship unavailable: %s", exc)
    return Collection(
        id=orm.id,
        collection_id=orm.collection_id,
        account_id=orm.account_id,
        name=orm.name,
        logo_filename=orm.logo_filename,
        created_at=orm.created_at,
        ip_address=orm.ip_address,
        account=account,
        documents=[],
    )


def account_to_orm(domain: DomainAccount) -> OrmAccount:
    """Convert domain Account to ORM Account."""
    from kapsula.infrastructure.data.tables.account import Account as OrmAccount

    return OrmAccount(
        id=domain.id,
        account_id=domain.account_id,
        name=domain.name,
        created_at=domain.created_at,
        ip_address=domain.ip_address,
    )


def account_from_orm(orm: OrmAccount) -> DomainAccount:
    """Convert ORM Account to domain Account (collections shallow, depth 2)."""
    from kapsula.core.domain.entities.account import Account

    colls = []
    try:
        if orm.collections:
            colls = [_collection_from_orm_shallow(c) for c in orm.collections]
    except (DetachedInstanceError, MissingGreenlet, AttributeError) as exc:
        logger.debug("Account.collections relationship unavailable: %s", exc)
    return Account(
        id=orm.id,
        account_id=orm.account_id,
        name=orm.name,
        created_at=orm.created_at,
        ip_address=orm.ip_address,
        collections=colls,
    )


def chunk_from_orm(orm: OrmChunk) -> DomainChunk:
    """Convert ORM Chunk to domain Chunk."""
    from kapsula.core.domain.entities.chunk import Chunk

    return Chunk(
        id=orm.id,
        document_id=orm.document_id,
        sub_document_id=orm.sub_document_id,
        content=orm.content,
        chunk_index=orm.chunk_index,
        token_count=orm.token_count,
        chunk_metadata=orm.chunk_metadata,
        created_at=orm.created_at,
    )


def sub_document_from_orm(orm: OrmSubDocument) -> DomainSubDocument:
    """Convert ORM SubDocument to domain SubDocument."""
    from kapsula.core.domain.entities.sub_document import SubDocument

    return SubDocument(
        id=orm.id,
        document_id=orm.document_id,
        breadcrumb_key=orm.breadcrumb_key,
        breadcrumb_level=orm.breadcrumb_level,
        faiss_index_path=orm.faiss_index_path,
        bm25_index_path=orm.bm25_index_path,
        page_count=orm.page_count,
        created_at=orm.created_at,
    )


# ── safe shallow mappers (no further nesting, break cycles) ──


def _collection_from_orm_safe(orm: OrmCollection) -> DomainCollection:
    """Collection with account (but account flat — no collections).

    Safe for Document→Collection→Account path.  Account has collections=[].
    """
    from kapsula.core.domain.entities.collection import Collection

    account = None
    try:
        if orm.account is not None:
            account = _account_from_orm_safe(orm.account)
    except (DetachedInstanceError, MissingGreenlet, AttributeError) as exc:
        logger.debug("Collection.account relationship unavailable (safe path): %s", exc)
    return Collection(
        id=orm.id,
        collection_id=orm.collection_id,
        account_id=orm.account_id,
        name=orm.name,
        logo_filename=orm.logo_filename,
        created_at=orm.created_at,
        ip_address=orm.ip_address,
        account=account,
        documents=[],
    )


def _account_from_orm_safe(orm: OrmAccount) -> DomainAccount:
    """Account without collections (safe for Collection→Account path)."""
    from kapsula.core.domain.entities.account import Account

    return Account(
        id=orm.id,
        account_id=orm.account_id,
        name=orm.name,
        created_at=orm.created_at,
        ip_address=orm.ip_address,
        collections=[],
    )


def _collection_from_orm_shallow(orm: OrmCollection) -> DomainCollection:
    """Collection without account (safe for Account→Collection[] path)."""
    from kapsula.core.domain.entities.collection import Collection

    return Collection(
        id=orm.id,
        collection_id=orm.collection_id,
        account_id=orm.account_id,
        name=orm.name,
        logo_filename=orm.logo_filename,
        created_at=orm.created_at,
        ip_address=orm.ip_address,
        account=None,
        documents=[],
    )


# ── read-model mappers (ORM → application DTOs for search) ───────


def sub_document_to_read(orm: OrmSubDocument) -> SubDocumentRead:
    """Project an ORM SubDocument to the search read-model DTO."""
    from kapsula.core.domain.read_models.sub_document_read import SubDocumentRead

    return SubDocumentRead(
        id=orm.id,
        breadcrumb_key=orm.breadcrumb_key,
        page_count=orm.page_count,
        faiss_index_path=orm.faiss_index_path,
        bm25_index_path=orm.bm25_index_path,
    )


def document_to_read(orm: OrmDocument) -> DocumentRead:
    """Project an ORM Document to the search read-model DTO."""
    from kapsula.core.domain.read_models.document_read import DocumentRead

    return DocumentRead(
        id=orm.id,
        filename=orm.filename,
        collection_id=orm.collection_id,
        faiss_index_path=orm.faiss_index_path,
        bm25_index_path=orm.bm25_index_path,
    )


def collection_to_read(orm: OrmCollection) -> CollectionRead:
    """Project an ORM Collection to the search read-model DTO."""
    from kapsula.core.domain.read_models.collection_read import CollectionRead

    account_guid = None
    try:
        if orm.account is not None:
            account_guid = orm.account.account_id
    except (DetachedInstanceError, MissingGreenlet, AttributeError) as exc:
        logger.debug("Collection.account relationship unavailable (read): %s", exc)
    return CollectionRead(
        id=orm.id,
        name=orm.name,
        collection_id=orm.collection_id,
        account_id=orm.account_id,
        account_guid=account_guid,
    )


def library_card_from_orm(orm):
    """Convert ORM LibraryCard to domain LibraryCard.

    Closes D4: previously ``SqlLibraryCardRepository`` mapped inline.
    """
    from kapsula.core.domain.entities.library_card import LibraryCard

    return LibraryCard(
        id=orm.id,
        collection_id=orm.collection_id,
        document_id=orm.document_id,
        sub_document_id=orm.sub_document_id,
        doc_id=orm.doc_id,
        level=orm.level,
        title=orm.title,
        content=orm.content,
        extra_metadata=orm.extra_metadata,
        created_at=orm.created_at,
    )


# ── read-model mappers for chunk / library-card search projections ──


def chunk_to_read(orm: OrmChunk) -> ChunkRead:
    """Project an ORM Chunk to the search read-model DTO (closes M5)."""
    from kapsula.core.domain.read_models.chunk_read import ChunkRead

    return ChunkRead(
        id=orm.id,
        document_id=orm.document_id,
        sub_document_id=orm.sub_document_id,
        chunk_index=orm.chunk_index,
        content=orm.content,
        token_count=orm.token_count,
        chunk_metadata=orm.chunk_metadata,
    )


def library_card_to_read(orm) -> LibraryCardRead:
    """Project an ORM LibraryCard to the search read-model DTO (closes M5)."""
    from kapsula.core.domain.read_models.library_card_read import LibraryCardRead

    return LibraryCardRead(
        id=orm.id,
        doc_id=orm.doc_id,
        level=orm.level,
        title=orm.title,
        content=orm.content,
        extra_metadata=orm.extra_metadata,
        collection_id=orm.collection_id,
        document_id=orm.document_id,
        sub_document_id=orm.sub_document_id,
        description=getattr(orm, "description", None),
        card_type=getattr(orm, "card_type", None),
        importance=getattr(orm, "importance", None),
    )
