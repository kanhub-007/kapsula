"""API request and response models.

Compatibility re-export module for API DTOs. Keep concrete DTO classes in
``doc_search.presentation.api.dto`` with one class per file.
"""

from doc_search.presentation.api.dto.upload_request import (
    UploadRequest as UploadRequest,
)
from doc_search.presentation.api.dto.upload_response import (
    UploadResponse as UploadResponse,
)
from doc_search.presentation.api.dto.progress_response import (
    ProgressResponse as ProgressResponse,
)
from doc_search.presentation.api.dto.collection_create import (
    CollectionCreate as CollectionCreate,
)
from doc_search.presentation.api.dto.collection_response import (
    CollectionResponse as CollectionResponse,
)
from doc_search.presentation.api.dto.collection_list_response import (
    CollectionListResponse as CollectionListResponse,
)
from doc_search.presentation.api.dto.document_info import DocumentInfo as DocumentInfo
from doc_search.presentation.api.dto.chunk_info import ChunkInfo as ChunkInfo
from doc_search.presentation.api.dto.chunks_download_response import (
    ChunksDownloadResponse as ChunksDownloadResponse,
)
from doc_search.presentation.api.dto.document_list_item import (
    DocumentListItem as DocumentListItem,
)
from doc_search.presentation.api.dto.document_list_response import (
    DocumentListResponse as DocumentListResponse,
)
from doc_search.presentation.api.dto.document_detail_response import (
    DocumentDetailResponse as DocumentDetailResponse,
)
from doc_search.presentation.api.dto.citation import Citation as Citation
from doc_search.presentation.api.dto.search_request import (
    SearchRequest as SearchRequest,
)
from doc_search.presentation.api.dto.search_result import SearchResult as SearchResult
from doc_search.presentation.api.dto.search_response import (
    SearchResponse as SearchResponse,
)
from doc_search.presentation.api.dto.collection_search_request import (
    CollectionSearchRequest as CollectionSearchRequest,
)
from doc_search.presentation.api.dto.collection_search_response import (
    CollectionSearchResponse as CollectionSearchResponse,
)
from doc_search.presentation.api.dto.sub_answer import SubAnswer as SubAnswer
from doc_search.presentation.api.dto.search_plan import SearchPlan as SearchPlan
from doc_search.presentation.api.dto.intelligent_search_response import (
    IntelligentSearchResponse as IntelligentSearchResponse,
)
from doc_search.presentation.api.dto.intelligent_collection_search_response import (
    IntelligentCollectionSearchResponse as IntelligentCollectionSearchResponse,
)
from doc_search.presentation.api.dto.streaming_progress_event import (
    StreamingProgressEvent as StreamingProgressEvent,
)
from doc_search.presentation.api.dto.library_card_info import (
    LibraryCardInfo as LibraryCardInfo,
)
from doc_search.presentation.api.dto.document_export_info import (
    DocumentExportInfo as DocumentExportInfo,
)
from doc_search.presentation.api.dto.collection_export_info import (
    CollectionExportInfo as CollectionExportInfo,
)
from doc_search.presentation.api.dto.account_export_response import (
    AccountExportResponse as AccountExportResponse,
)
from doc_search.presentation.api.dto.account_create import (
    AccountCreate as AccountCreate,
)
from doc_search.presentation.api.dto.account_response import (
    AccountResponse as AccountResponse,
)
from doc_search.presentation.api.dto.account_list_response import (
    AccountListResponse as AccountListResponse,
)

__all__ = [
    "UploadRequest",
    "UploadResponse",
    "ProgressResponse",
    "CollectionCreate",
    "CollectionResponse",
    "CollectionListResponse",
    "DocumentInfo",
    "ChunkInfo",
    "ChunksDownloadResponse",
    "DocumentListItem",
    "DocumentListResponse",
    "DocumentDetailResponse",
    "Citation",
    "SearchRequest",
    "SearchResult",
    "SearchResponse",
    "CollectionSearchRequest",
    "CollectionSearchResponse",
    "SubAnswer",
    "SearchPlan",
    "IntelligentSearchResponse",
    "IntelligentCollectionSearchResponse",
    "StreamingProgressEvent",
    "LibraryCardInfo",
    "DocumentExportInfo",
    "CollectionExportInfo",
    "AccountExportResponse",
    "AccountCreate",
    "AccountResponse",
    "AccountListResponse",
]
