"""Mappers between domain entities and ORM models.

Every function converts ONE direction, ONE level deep.
Nested relationships are NOT eagerly mapped to avoid cycles.
"""

from __future__ import annotations


def document_to_orm(domain):
    """Convert domain Document to ORM Document for persistence."""
    from doc_search.infrastructure.data.tables.document import Document as OrmDocument
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


def document_from_orm(orm) -> "domain_doc.Document":
    """Convert ORM Document to domain Document (flat, no nested collections)."""
    from doc_search.core.domain.entities.document import Document
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
        collection=None,
        chunks=[],
        sub_documents=[],
    )


def collection_to_orm(domain):
    """Convert domain Collection to ORM Collection."""
    from doc_search.infrastructure.data.tables.collection import Collection as OrmCollection
    return OrmCollection(
        id=domain.id,
        collection_id=domain.collection_id,
        account_id=domain.account_id,
        name=domain.name,
        logo_filename=domain.logo_filename,
        created_at=domain.created_at,
        ip_address=domain.ip_address,
    )


def collection_from_orm(orm) -> "domain_coll.Collection":
    """Convert ORM Collection to domain Collection (flat)."""
    from doc_search.core.domain.entities.collection import Collection
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


def account_to_orm(domain):
    """Convert domain Account to ORM Account."""
    from doc_search.infrastructure.data.tables.account import Account as OrmAccount
    return OrmAccount(
        id=domain.id,
        account_id=domain.account_id,
        name=domain.name,
        created_at=domain.created_at,
        ip_address=domain.ip_address,
    )


def account_from_orm(orm) -> "domain_acct.Account":
    """Convert ORM Account to domain Account (flat)."""
    from doc_search.core.domain.entities.account import Account
    return Account(
        id=orm.id,
        account_id=orm.account_id,
        name=orm.name,
        created_at=orm.created_at,
        ip_address=orm.ip_address,
        collections=[],
    )


def chunk_from_orm(orm) -> "domain_chunk.Chunk":
    """Convert ORM Chunk to domain Chunk."""
    from doc_search.core.domain.entities.chunk import Chunk
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


def sub_document_from_orm(orm) -> "domain_sd.SubDocument":
    """Convert ORM SubDocument to domain SubDocument."""
    from doc_search.core.domain.entities.sub_document import SubDocument
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
