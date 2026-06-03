"""Composition root — wires all dependencies for API and MCP entry points."""

import os
import uuid

from dotenv import load_dotenv

from doc_search.infrastructure.data.connection import init_db, SessionLocal
from doc_search.infrastructure.data.tables.account import Account
from doc_search.infrastructure.logging_config import get_logger

load_dotenv()
logger = get_logger(__name__)


def bootstrap():
    """Initialize database and default account. Call once at startup."""
    init_db()
    logger.info("Database tables initialized")

    db = SessionLocal()
    try:
        existing = db.query(Account).filter(Account.name == "doc-search").first()
        if not existing:
            account = Account(
                account_id=str(uuid.uuid4()),
                name="doc-search",
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
    from doc_search.infrastructure.repositories.embedding.caching_embedder import (
        CachingEmbedder,
    )
    from doc_search.infrastructure.repositories.embedding.huggingface_embedder import (
        HuggingFaceEmbedder,
    )

    endpoint_url = os.getenv("EMBEDDING_MODEL_URL", "Qwen/Qwen3-Embedding-8B")
    embedder = HuggingFaceEmbedder(
        endpoint_url=endpoint_url,
        token=os.getenv("HF_API_TOKEN") or os.getenv("HF_TOKEN", ""),
    )
    return CachingEmbedder(embedder, namespace=endpoint_url, max_entries=256)


def create_chat_client():
    from doc_search.infrastructure.external.llm.chat_client import HuggingFaceChatClient

    token = os.getenv("HF_API_TOKEN") or os.getenv("HF_TOKEN", "")
    model = os.getenv("INTELLIGENT_SEARCH_MODEL", "deepseek-ai/DeepSeek-V3.2-Exp")
    return HuggingFaceChatClient(token=token, model=model)


def create_reranker():
    from doc_search.infrastructure.repositories.reranking.local_cross_encoder_reranker import (
        LocalCrossEncoderReranker,
    )

    return LocalCrossEncoderReranker(
        model_name=os.getenv("RERANKER_MODEL", "mixedbread-ai/mxbai-rerank-large-v1")
    )


def create_intelligent_searcher(chat_client=None):
    from doc_search.core.application.use_cases.intelligent_searcher import (
        IntelligentSearcher,
    )

    client = chat_client or create_chat_client()
    return IntelligentSearcher(client)


def create_query_planner(chat_client=None):
    from doc_search.core.application.use_cases.planning.query_planner import (
        QueryPlanner,
    )

    client = chat_client or create_chat_client()
    return QueryPlanner(client)


def create_collection_summary_generator(chat_client=None):
    from doc_search.core.application.use_cases.collection_summary import (
        CollectionSummaryGenerator,
    )

    client = chat_client or create_chat_client()
    return CollectionSummaryGenerator(client)


def create_multi_index_searcher(
    db_session=None, embedder=None, reranker=None, chat_client=None
):
    from doc_search.infrastructure.repositories.data.sql_search_data_access import (
        SqlSearchDataAccess,
    )
    from doc_search.startup.hybrid_searcher_factory import HybridSearcherFactory
    from doc_search.core.application.use_cases.multi_index_searcher import (
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
        aggregate_strategy=create_aggregate_search_strategy(embedder),
        account_strategy=create_account_search_strategy(embedder),
    )


def create_aggregate_search_strategy(embedder=None):
    from doc_search.infrastructure.data.connection import DATA_DIR
    from doc_search.infrastructure.repositories.indexing.aggregate_index_search_strategy import (
        AggregateIndexSearchStrategy,
    )

    embedder = embedder or create_embedder()
    return AggregateIndexSearchStrategy(data_dir=DATA_DIR, embedder=embedder)


def create_account_search_strategy(embedder=None):
    from doc_search.infrastructure.data.connection import DATA_DIR
    from doc_search.infrastructure.repositories.indexing.account_index_search_strategy import (
        AccountIndexSearchStrategy,
    )

    embedder = embedder or create_embedder()
    return AccountIndexSearchStrategy(data_dir=DATA_DIR, embedder=embedder)
