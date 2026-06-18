"""FAISS and BM25 index loaders."""

import os
import pickle
from typing import Any

import faiss

from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


def load_faiss_index(index_path: str) -> faiss.Index:
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"FAISS index not found: {index_path}")
    index = faiss.read_index(index_path)
    logger.debug(f"Loaded FAISS index with {index.ntotal} vectors")
    return index


def load_bm25_index(index_path: str) -> tuple[Any, list[str]]:
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"BM25 index not found: {index_path}")
    with open(index_path, "rb") as f:
        data = pickle.load(f)
    logger.debug(f"Loaded BM25 index with {len(data['texts'])} documents")
    return data["bm25"], data["texts"]
