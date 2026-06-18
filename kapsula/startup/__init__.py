"""Composition root — wires all dependencies for API and MCP entry points."""

import os
import uuid

from dotenv import load_dotenv

from kapsula.infrastructure.data.connection import init_db, SessionLocal
from kapsula.infrastructure.data.tables.account import Account
from kapsula.infrastructure.logging_config import get_logger

load_dotenv()
logger = get_logger(__name__)


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


def create_chat_client():
    from kapsula.infrastructure.external.llm.chat_client import HuggingFaceChatClient

    token = os.getenv("HF_API_TOKEN") or os.getenv("HF_TOKEN", "")
    model = os.getenv("INTELLIGENT_SEARCH_MODEL", "deepseek-ai/DeepSeek-V3.2-Exp")
    return HuggingFaceChatClient(token=token, model=model)


def create_reranker():
    from kapsula.infrastructure.repositories.reranking.local_cross_encoder_reranker import (
        LocalCrossEncoderReranker,
    )

    return LocalCrossEncoderReranker(
        model_name=os.getenv("RERANKER_MODEL", "mixedbread-ai/mxbai-rerank-large-v1")
    )


def create_intelligent_searcher(chat_client=None):
    from kapsula.core.application.use_cases.intelligent_searcher import (
        IntelligentSearcher,
    )

    client = chat_client or create_chat_client()
    return IntelligentSearcher(client)


def create_query_planner(chat_client=None):
    from kapsula.core.application.use_cases.planning.query_planner import (
        QueryPlanner,
    )

    client = chat_client or create_chat_client()
    return QueryPlanner(client)


def create_collection_summary_generator(chat_client=None):
    from kapsula.core.application.use_cases.collection_summary import (
        CollectionSummaryGenerator,
    )

    client = chat_client or create_chat_client()
    return CollectionSummaryGenerator(client)


def create_multi_index_searcher(
    db_session=None, embedder=None, reranker=None, chat_client=None
):
    from kapsula.infrastructure.repositories.data.sql_search_data_access import (
        SqlSearchDataAccess,
    )
    from kapsula.startup.hybrid_searcher_factory import HybridSearcherFactory
    from kapsula.core.application.use_cases.multi_index_searcher import (
        MultiIndexSearcher,
    )

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
    )


def _make_aggregate_searcher(faiss_index, bm25_index, texts, embedder):
    """Factory to create a HybridSearcher for aggregate index strategies.

    Kept in startup/ to avoid infrastructure importing from application.
    """
    from kapsula.core.application.use_cases.hybrid_searcher import HybridSearcher
    from kapsula.core.domain.fusion.weighted_fusion import WeightedFusion
    from kapsula.infrastructure.repositories.retrieval import DenseRetriever, SparseRetriever

    return HybridSearcher(
        dense=DenseRetriever(faiss_index, texts, embedder),
        sparse=SparseRetriever(bm25_index, texts),
        fusion=WeightedFusion(),
        reranker=None,
    )


def create_aggregate_search_strategy(embedder=None):
    from kapsula.infrastructure.data.connection import DATA_DIR
    from kapsula.infrastructure.repositories.indexing.aggregate_index_search_strategy import (
        AggregateIndexSearchStrategy,
    )
    from kapsula.core.domain.entities.aggregate_index_paths import (
        AggregateIndexPaths,
    )

    embedder = embedder or create_embedder()

    def _collection_paths(collection: dict):
        return AggregateIndexPaths.for_collection(
            DATA_DIR,
            account_guid=collection.get("account_guid"),
            collection_guid=collection.get("collection_guid"),
        )

    return AggregateIndexSearchStrategy(
        data_dir=DATA_DIR, embedder=embedder, path_factory=_collection_paths,
        searcher_factory=_make_aggregate_searcher,
    )


def create_account_search_strategy(embedder=None):
    from kapsula.infrastructure.data.connection import DATA_DIR
    from kapsula.infrastructure.repositories.indexing.aggregate_index_search_strategy import (
        AggregateIndexSearchStrategy,
    )
    from kapsula.core.domain.entities.aggregate_index_paths import (
        AggregateIndexPaths,
    )

    embedder = embedder or create_embedder()

    def _account_paths(collection: dict):
        guid = collection.get("account_guid")
        if not guid:
            return None
        return AggregateIndexPaths.for_account(DATA_DIR, guid)

    return AggregateIndexSearchStrategy(
        data_dir=DATA_DIR, embedder=embedder, path_factory=_account_paths,
        searcher_factory=_make_aggregate_searcher,
    )


def create_delete_document_use_case():
    """Create a DeleteDocumentUseCase with wired dependencies."""
    from kapsula.infrastructure.data.connection import DATA_DIR
    from kapsula.infrastructure.repositories.indexing.index_manager import (
        FileSystemIndexManager,
    )
    from kapsula.infrastructure.repositories.data.sql_document_repository import (
        SqlDocumentRepository,
    )
    from kapsula.core.application.use_cases.delete_document import (
        DeleteDocumentUseCase,
    )

    embedder = create_embedder()
    index_manager = FileSystemIndexManager(embedder, DATA_DIR)
    document_repository = SqlDocumentRepository()
    return DeleteDocumentUseCase(index_manager, document_repository)


def create_upload_document_use_case():
    """Create an UploadDocumentUseCase with wired dependencies."""
    from kapsula.infrastructure.repositories.processing.background_processor import (
        ThreadPoolBackgroundProcessor,
    )
    from kapsula.infrastructure.repositories.data.sql_document_repository import (
        SqlDocumentRepository,
    )
    from kapsula.infrastructure.repositories.processing.progress_tracker import (
        InMemoryProgressTracker,
    )
    from kapsula.core.application.use_cases.upload_document import (
        UploadDocumentUseCase,
    )

    background_processor = ThreadPoolBackgroundProcessor()
    document_repository = SqlDocumentRepository()
    progress_tracker = InMemoryProgressTracker()
    return UploadDocumentUseCase(background_processor, document_repository, progress_tracker)
