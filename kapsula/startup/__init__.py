"""Composition root — wires all dependencies for API and MCP entry points."""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from kapsula.infrastructure.data.connection import SessionLocal, init_db
from kapsula.infrastructure.data.tables.account import Account
from kapsula.infrastructure.logging_config import get_logger

if TYPE_CHECKING:
    from kapsula.core.domain.interfaces.chat_client import ChatClient
    from kapsula.core.domain.interfaces.embedder import Embedder
    from kapsula.core.domain.interfaces.reranker import Reranker

load_dotenv()
logger = get_logger(__name__)


# Module-level shared maintenance-state manager (single instance per process).
# Closes A3: previously constructed inline at 9 call sites, re-reading the
# JSON file on every call. The instance caches parsed state in memory and
# only flushes on write (PE1).
_maintenance_state_manager = None


def create_maintenance_state_manager():
    """Return the process-wide shared MaintenanceStateManager."""
    global _maintenance_state_manager
    if _maintenance_state_manager is None:
        from kapsula.infrastructure.repositories.processing.maintenance_state_manager import (
            MaintenanceStateManager,
        )

        _maintenance_state_manager = MaintenanceStateManager()
    return _maintenance_state_manager


def bootstrap():
    """Initialize database and default account. Call once at startup."""
    init_db()
    logger.info("Database tables initialized")

    db = SessionLocal()
    try:
        existing = db.query(Account).filter(Account.name == "kapsula").first()
        if not existing:
            account = Account(
                account_id=str(uuid.uuid4()),
                name="kapsula",
                ip_address="127.0.0.1",
            )
            db.add(account)
            db.commit()
            logger.info(f"Created default account: {account.account_id}")
        else:
            logger.info(f"Default account exists: {existing.account_id}")
    finally:
        db.close()


def create_embedder():
    from kapsula.infrastructure.repositories.embedding.caching_embedder import (
        CachingEmbedder,
    )
    from kapsula.infrastructure.repositories.embedding.huggingface_embedder import (
        HuggingFaceEmbedder,
    )

    endpoint_url = os.getenv("EMBEDDING_MODEL_URL", "Qwen/Qwen3-Embedding-8B")
    embedder = HuggingFaceEmbedder(
        endpoint_url=endpoint_url,
        token=os.getenv("HF_API_TOKEN") or os.getenv("HF_TOKEN", ""),
    )
    return CachingEmbedder(embedder, namespace=endpoint_url, max_entries=256)


def create_upload_pipeline(ingestion_mode: str):
    """Build the upload pipeline (chunking + ingestion strategies) for a mode.

    Returns ``(pipeline, ingestion_strategy)`` so the caller can build a
    context and dispatch. The chunking strategy is SubDocument-by-default
    (falls back to flat internally when no breadcrumbs exist).
    """
    from kapsula.infrastructure.repositories.processing.upload_strategies import (
        SubDocumentChunkingStrategy,
        UploadIngestionStrategyFactory,
        UploadPipeline,
    )

    ingestion = UploadIngestionStrategyFactory.create(ingestion_mode)
    chunking = SubDocumentChunkingStrategy()
    return UploadPipeline(chunking, ingestion), ingestion


def create_chat_client():
    from kapsula.infrastructure.external.llm.chat_client import HuggingFaceChatClient

    token = os.getenv("HF_API_TOKEN") or os.getenv("HF_TOKEN", "")
    model = os.getenv("INTELLIGENT_SEARCH_MODEL", "deepseek-ai/DeepSeek-V3.2-Exp")
    return HuggingFaceChatClient(token=token, model=model)


# Process-wide cached chat client for presentation layers that cannot wire
# dependencies through the composition root on every call (background
# maintenance runner, MCP tool modules). Cheap to share: stateless wrapper.
_shared_chat_client = None


def get_shared_chat_client():
    """Return a process-wide cached :class:`ChatClient` (closes H9).

    Used by presentation modules (maintenance runner) so they no longer
    reach into the MCP tools package for a chat client. Created lazily on
    first access.
    """
    global _shared_chat_client
    if _shared_chat_client is None:
        _shared_chat_client = create_chat_client()
    return _shared_chat_client


def create_reranker():
    from kapsula.infrastructure.repositories.reranking.local_cross_encoder_reranker import (
        LocalCrossEncoderReranker,
    )

    return LocalCrossEncoderReranker(
        model_name=os.getenv("RERANKER_MODEL", "mixedbread-ai/mxbai-rerank-large-v1")
    )


def create_intelligent_searcher(chat_client: ChatClient | None = None):
    from kapsula.core.application.use_cases.intelligent_searcher import (
        IntelligentSearcher,
    )

    client = chat_client or create_chat_client()
    return IntelligentSearcher(client)


def _build_collection_document_structure(db, collection_id: int) -> list[dict]:
    """Build hierarchical document structure for a collection (shared helper).

    Used by :func:`create_prepare_intelligent_search_use_case` so both the
    API and MCP paths share one structure-building implementation.
    """
    from kapsula.infrastructure.data import Document as OrmDocument
    from kapsula.infrastructure.data import SubDocument as OrmSubDocument
    from kapsula.presentation.shared.document_structure_builder import (
        build_document_structure_from_subdocs,
    )

    structure: list[dict] = []
    documents = (
        db.query(OrmDocument).filter(OrmDocument.collection_id == collection_id).all()
    )
    for doc in documents:
        subdocs = (
            db.query(OrmSubDocument).filter(OrmSubDocument.document_id == doc.id).all()
        )
        structure.extend(build_document_structure_from_subdocs(subdocs, db))
    return structure


def create_prepare_intelligent_search_use_case(db):
    """Wire the shared intelligent-search preparation use case (closes A6)."""
    from kapsula.core.application.use_cases.prepare_intelligent_search import (
        PrepareIntelligentSearchUseCase,
    )
    from kapsula.core.application.use_cases.selectors.collection_selector import (
        CollectionSelector,
    )
    from kapsula.infrastructure.repositories.data.sql_search_data_access import (
        SqlSearchDataAccess,
    )

    chat_client = create_chat_client()
    data = SqlSearchDataAccess(db)
    return PrepareIntelligentSearchUseCase(
        data=data,
        chat_client=chat_client,
        query_planner=create_query_planner(chat_client),
        collection_selector=CollectionSelector(chat_client),
        structure_builder=lambda cid: _build_collection_document_structure(db, cid),
    )


def create_query_planner(chat_client: ChatClient | None = None):
    from kapsula.core.application.use_cases.planning.query_planner import (
        QueryPlanner,
    )

    client = chat_client or create_chat_client()
    return QueryPlanner(client)


def create_collection_summary_generator(chat_client: ChatClient | None = None):
    from kapsula.core.application.use_cases.collection_summary import (
        CollectionSummaryGenerator,
    )

    client = chat_client or create_chat_client()
    return CollectionSummaryGenerator(client)


def create_multi_index_searcher(
    db_session=None,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    chat_client: ChatClient | None = None,
):
    from kapsula.core.application.use_cases.multi_index_searcher import (
        MultiIndexSearcher,
    )
    from kapsula.infrastructure.repositories.data.sql_search_data_access import (
        SqlSearchDataAccess,
    )
    from kapsula.startup.hybrid_searcher_factory import HybridSearcherFactory

    data = SqlSearchDataAccess(db_session) if db_session else None
    embedder = embedder or create_embedder()
    reranker = reranker or create_reranker()
    chat_client = chat_client or create_chat_client()
    factory = HybridSearcherFactory()

    def make_searcher(faiss_path, bm25_path):
        return factory.create(
            faiss_index_path=faiss_path,
            bm25_index_path=bm25_path,
            embedder=embedder,
            reranker=reranker,
        )

    return MultiIndexSearcher(
        data=data,
        embedder=embedder,
        reranker=reranker,
        chat_client=chat_client,
        make_searcher=make_searcher,
        strategies=[
            create_aggregate_search_strategy(embedder),
            create_account_search_strategy(embedder),
        ],
        document_concurrency=_document_concurrency_from_env(),
    )


def _document_concurrency_from_env() -> int:
    """Read KAPSULA_DOCUMENT_CONCURRENCY once at wiring time (not per search)."""
    from kapsula.core.application.use_cases.search_runtime_helpers import (
        DEFAULT_DOCUMENT_CONCURRENCY,
    )

    raw = os.getenv("KAPSULA_DOCUMENT_CONCURRENCY")
    if not raw:
        return DEFAULT_DOCUMENT_CONCURRENCY
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "Invalid KAPSULA_DOCUMENT_CONCURRENCY=%r; falling back to %s",
            raw,
            DEFAULT_DOCUMENT_CONCURRENCY,
        )
        return DEFAULT_DOCUMENT_CONCURRENCY


def _make_aggregate_searcher(faiss_index, bm25_index, texts, embedder):
    """Factory to create a HybridSearcher for aggregate index strategies.

    Kept in startup/ to avoid infrastructure importing from application.
    """
    from kapsula.core.application.use_cases.hybrid_searcher import HybridSearcher
    from kapsula.core.domain.fusion.weighted_fusion import WeightedFusion
    from kapsula.infrastructure.repositories.retrieval import (
        DenseRetriever,
        SparseRetriever,
    )

    return HybridSearcher(
        dense=DenseRetriever(faiss_index, texts, embedder),
        sparse=SparseRetriever(bm25_index, texts),
        fusion=WeightedFusion(),
        reranker=None,
    )


def create_aggregate_search_strategy(embedder=None):
    from kapsula.core.domain.entities.aggregate_index_paths import (
        AggregateIndexPaths,
    )
    from kapsula.infrastructure.data.connection import DATA_DIR
    from kapsula.infrastructure.repositories.indexing.aggregate_index_search_strategy import (
        AggregateIndexSearchStrategy,
    )

    embedder = embedder or create_embedder()

    def _collection_paths(collection: dict):
        return AggregateIndexPaths.for_collection(
            DATA_DIR,
            account_guid=collection.get("account_guid"),
            collection_guid=collection.get("collection_guid"),
        )

    return AggregateIndexSearchStrategy(
        data_dir=DATA_DIR,
        embedder=embedder,
        path_factory=_collection_paths,
        searcher_factory=_make_aggregate_searcher,
    )


def create_account_search_strategy(embedder=None):
    from kapsula.core.domain.entities.aggregate_index_paths import (
        AggregateIndexPaths,
    )
    from kapsula.infrastructure.data.connection import DATA_DIR
    from kapsula.infrastructure.repositories.indexing.aggregate_index_search_strategy import (
        AggregateIndexSearchStrategy,
    )

    embedder = embedder or create_embedder()

    def _account_paths(collection: dict):
        guid = collection.get("account_guid")
        if not guid:
            return None
        return AggregateIndexPaths.for_account(DATA_DIR, guid)

    return AggregateIndexSearchStrategy(
        data_dir=DATA_DIR,
        embedder=embedder,
        path_factory=_account_paths,
        searcher_factory=_make_aggregate_searcher,
    )


def create_search_single_document_use_case(db_session=None):
    """Wire SearchSingleDocumentUseCase (closes H5).

    The searcher is built per-call against the request's DB session.
    """
    from kapsula.core.application.use_cases.search_single_document import (
        SearchSingleDocumentUseCase,
    )
    from kapsula.infrastructure.repositories.data.sql_document_repository import (
        SqlDocumentRepository,
    )

    def make_searcher():
        return create_multi_index_searcher(db_session)

    return SearchSingleDocumentUseCase(SqlDocumentRepository(), make_searcher)


def create_delete_document_use_case():
    """Create a DeleteDocumentUseCase with wired dependencies."""
    from kapsula.core.application.use_cases.delete_document import (
        DeleteDocumentUseCase,
    )
    from kapsula.infrastructure.data.connection import DATA_DIR
    from kapsula.infrastructure.repositories.data.sql_document_repository import (
        SqlDocumentRepository,
    )
    from kapsula.infrastructure.repositories.indexing.index_manager import (
        FileSystemIndexManager,
    )

    embedder = create_embedder()
    index_manager = FileSystemIndexManager(embedder, DATA_DIR)
    document_repository = SqlDocumentRepository()
    return DeleteDocumentUseCase(
        index_manager,
        document_repository,
        create_maintenance_state_manager(),
    )


def create_upload_document_use_case():
    """Create an UploadDocumentUseCase for the MCP path.

    Wires a real ``ThreadPoolBackgroundProcessor`` so the MCP tool returns
    immediately while the document is processed in a daemon thread.
    """
    from kapsula.core.application.use_cases.upload_document import (
        UploadDocumentUseCase,
    )
    from kapsula.infrastructure.repositories.data.sql_document_repository import (
        SqlDocumentRepository,
    )
    from kapsula.infrastructure.repositories.data.sql_upload_job_repository import (
        SqlUploadJobRepository,
    )
    from kapsula.infrastructure.repositories.processing.background_processor import (
        ThreadPoolBackgroundProcessor,
    )
    from kapsula.infrastructure.repositories.processing.progress_tracker import (
        UploadProgressTracker,
    )

    # The background task lives in presentation; the composition root (here)
    # is the only layer allowed to wire presentation into infrastructure,
    # so ThreadPoolBackgroundProcessor never imports presentation itself.
    from kapsula.presentation.api.tasks import process_document_with_subdocuments

    background_processor = ThreadPoolBackgroundProcessor(
        process_document_with_subdocuments
    )
    document_repository = SqlDocumentRepository()
    job_repository = SqlUploadJobRepository()
    progress_tracker = UploadProgressTracker(job_repository)
    return UploadDocumentUseCase(
        background_processor,
        document_repository,
        progress_tracker,
        create_maintenance_state_manager(),
    )


def create_api_upload_document_use_case():
    """Create an UploadDocumentUseCase for the HTTP API path.

    Wires a ``NoOpBackgroundProcessor`` because the HTTP route dispatches
    the task itself via FastAPI ``BackgroundTasks`` (per the
    ``wire-upload-usecase`` spec). If the use case also dispatched, every
    upload would be processed twice (duplicate chunks, duplicate indexes,
    races on shared state).
    """
    from kapsula.core.application.use_cases.upload_document import (
        UploadDocumentUseCase,
    )
    from kapsula.infrastructure.repositories.data.sql_document_repository import (
        SqlDocumentRepository,
    )
    from kapsula.infrastructure.repositories.data.sql_upload_job_repository import (
        SqlUploadJobRepository,
    )
    from kapsula.infrastructure.repositories.processing.background_processor import (
        NoOpBackgroundProcessor,
    )
    from kapsula.infrastructure.repositories.processing.progress_tracker import (
        UploadProgressTracker,
    )

    document_repository = SqlDocumentRepository()
    job_repository = SqlUploadJobRepository()
    progress_tracker = UploadProgressTracker(job_repository)
    return UploadDocumentUseCase(
        NoOpBackgroundProcessor(),
        document_repository,
        progress_tracker,
        create_maintenance_state_manager(),
    )
