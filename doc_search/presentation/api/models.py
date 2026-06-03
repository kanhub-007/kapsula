"""API request and response models."""

from typing import Optional, List, Dict, Any

from pydantic import BaseModel


# Collection Models
class CollectionCreate(BaseModel):
    """Request model for creating a collection."""

    name: str
    account_id: Optional[str] = None  # Optional account ID to link collection to


class CollectionResponse(BaseModel):
    """Response model for collection."""

    collection_id: str
    name: str
    logo_url: Optional[str] = None
    created_at: str
    document_count: int
    # Optional summarized library card for the collection (not per-document)
    library_card_summary: Optional[str] = None


class CollectionListResponse(BaseModel):
    """Response model for collection list."""

    collections: List[CollectionResponse]
    total: int


class UploadRequest(BaseModel):
    """Request model for document upload."""

    collection_id: str
    max_tokens: Optional[int] = 512


class UploadResponse(BaseModel):
    """Response model for document upload."""

    job_id: str
    collection_id: str
    status: str
    message: str


class ProgressResponse(BaseModel):
    """Response model for progress tracking."""

    status: str
    progress: int
    stage: str
    message: str
    chunk_count: Optional[int] = None
    duration: Optional[float] = None


class DocumentInfo(BaseModel):
    """Document metadata information."""

    id: int
    job_id: str
    filename: str
    size: int
    created_at: str
    duration: Optional[float]
    ip_address: str


class ChunkInfo(BaseModel):
    """Chunk information."""

    id: int
    chunk_index: int
    content: str
    token_count: Optional[int]
    metadata: Dict[str, Any]


class ChunksDownloadResponse(BaseModel):
    """Response model for downloading chunks as JSON."""

    document: DocumentInfo
    chunks: List[ChunkInfo]
    total_chunks: int


class DocumentListItem(BaseModel):
    """Document list item."""

    id: int
    job_id: str
    collection_id: str
    collection_name: str
    filename: str
    size: int
    status: str
    created_at: str
    duration: Optional[float]
    chunk_count: int


class DocumentListResponse(BaseModel):
    """Response model for document list."""

    documents: List[DocumentListItem]
    total: int


class DocumentDetailResponse(BaseModel):
    """Response model for document details."""

    id: int
    job_id: str
    collection_id: str
    collection_name: str
    filename: str
    size: int
    status: str
    created_at: str
    duration: Optional[float]
    ip_address: str
    chunk_count: int
    structure: Optional[str]  # Markdown skeleton structure


# Search Models
class Citation(BaseModel):
    """Citation information for tracing chunk origin."""

    library_card_id: Optional[int] = None
    start_char: int
    end_char: int
    section_title: str
    section_level: str  # level_1, level_2, or level_3


class SearchRequest(BaseModel):
    """Request model for search."""

    query: str
    top_k: Optional[int] = 10
    dense_weight: Optional[float] = 0.5
    sparse_weight: Optional[float] = 0.5
    rerank: Optional[bool] = False


class SearchResult(BaseModel):
    """Single search result."""

    index: int
    content: str
    score: float
    dense_score: float
    sparse_score: float
    rerank_score: Optional[float] = None  # Shows reranker score if reranking enabled
    sub_document_key: Optional[str] = (
        None  # Shows which sub-document this result came from
    )
    contributing_chunks: Optional[List[int]] = (
        None  # Chunk indices that contributed to this result (for deduplicated parents)
    )
    parent_hash: Optional[str] = (
        None  # Parent section hash (when context expansion is used)
    )
    collection_name: Optional[str] = (
        None  # Collection name (for collection-level search)
    )
    document_filename: Optional[str] = (
        None  # Document filename (for collection-level search)
    )
    retrieval_score: Optional[float] = None  # Original score before route weighting
    collection_route_confidence: Optional[float] = None
    subdocument_route_confidence: Optional[float] = None
    metadata_route_confidence: Optional[float] = None
    citation: Optional[Citation] = None  # Citation information for tracing origin


class SearchResponse(BaseModel):
    """Response model for search."""

    job_id: str
    query: str
    total_results: int
    results: List[SearchResult]
    context_mode: Optional[str] = None
    node_type_filter: Optional[List[str]] = None
    citations: Optional[List[Citation]] = (
        None  # All unique citations from search results
    )


class CollectionSearchRequest(BaseModel):
    """Request model for collection-level search."""

    query: str
    account_id: Optional[str] = None
    top_k: Optional[int] = 10
    rerank: Optional[bool] = False
    context_mode: Optional[str] = "none"


class CollectionSearchResponse(BaseModel):
    """Response model for collection-level search."""

    query: str
    account_id: Optional[str] = None
    collection_id: Optional[str] = None
    total_results: int
    results: List[SearchResult]
    context_mode: Optional[str] = None
    citations: Optional[List[Citation]] = (
        None  # All unique citations from search results
    )


class SubAnswer(BaseModel):
    """Answer to a sub-question generated by the planner."""

    question: str
    answer: str
    has_answer: bool
    num_results: int


class SearchPlan(BaseModel):
    """Search plan generated by query planner."""

    strategy: str
    queries: List[str]
    reasoning: str
    total_unique_results: Optional[int] = None
    sub_answers_count: Optional[int] = None


class IntelligentSearchResponse(BaseModel):
    """Response model for intelligent search on document."""

    job_id: str
    query: str
    answer: str
    has_answer: bool
    relevant_results: List[int]
    total_evaluated: int
    context_mode: Optional[str] = None
    plan: Optional[SearchPlan] = None
    sub_answers: Optional[List[SubAnswer]] = None
    citations: Optional[List[Citation]] = (
        None  # All unique citations from search results
    )


class IntelligentCollectionSearchResponse(BaseModel):
    """Response model for intelligent search on collections."""

    query: str
    account_id: Optional[str] = None
    answer: str
    has_answer: bool
    relevant_results: List[int]
    total_evaluated: int
    context_mode: Optional[str] = None
    plan: Optional[SearchPlan] = None
    sub_answers: Optional[List[SubAnswer]] = None
    citations: Optional[List[Citation]] = (
        None  # All unique citations from search results
    )


class StreamingProgressEvent(BaseModel):
    """Streaming event for intelligent search progress updates."""

    event_type: (
        str  # 'planning', 'subquestion_start', 'subquestion_complete', 'final_answer'
    )
    data: Dict[str, Any]  # Event-specific data


# Account Export Models
class LibraryCardInfo(BaseModel):
    """Library card information."""

    id: int
    level: str
    title: str
    content: str
    created_at: str


class DocumentExportInfo(BaseModel):
    """Complete document information for export."""

    id: int
    job_id: str
    filename: str
    size: int
    status: str
    created_at: str
    duration: Optional[float]
    chunk_count: int
    library_cards: List[LibraryCardInfo]


class CollectionExportInfo(BaseModel):
    """Complete collection information for export."""

    collection_id: str
    name: str
    logo_url: Optional[str] = None
    created_at: str
    document_count: int
    documents: List[DocumentExportInfo]
    library_cards: List[LibraryCardInfo]  # Collection-level library cards


class AccountExportResponse(BaseModel):
    """Complete account export with all data."""

    account_id: str
    name: str
    created_at: str
    collection_count: int
    total_documents: int
    total_library_cards: int
    collections: List[CollectionExportInfo]
