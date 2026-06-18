"""API request and response models.

Compatibility re-export module for API DTOs. Keep concrete DTO classes in
``kapsula.presentation.api.dto`` with one class per file.
"""

from kapsula.presentation.api.dto.account_create import (
    AccountCreate as AccountCreate,
)
from kapsula.presentation.api.dto.account_export_response import (
    AccountExportResponse as AccountExportResponse,
)
from kapsula.presentation.api.dto.account_list_response import (
    AccountListResponse as AccountListResponse,
)
from kapsula.presentation.api.dto.account_response import (
    AccountResponse as AccountResponse,
)
from kapsula.presentation.api.dto.chunk_info import ChunkInfo as ChunkInfo
from kapsula.presentation.api.dto.chunks_download_response import (
    ChunksDownloadResponse as ChunksDownloadResponse,
)
from kapsula.presentation.api.dto.citation import Citation as Citation
from kapsula.presentation.api.dto.collection_create import (
    CollectionCreate as CollectionCreate,
)
from kapsula.presentation.api.dto.collection_export_info import (
    CollectionExportInfo as CollectionExportInfo,
)
from kapsula.presentation.api.dto.collection_list_response import (
    CollectionListResponse as CollectionListResponse,
)
from kapsula.presentation.api.dto.collection_response import (
    CollectionResponse as CollectionResponse,
)
from kapsula.presentation.api.dto.collection_search_request import (
    CollectionSearchRequest as CollectionSearchRequest,
)
from kapsula.presentation.api.dto.collection_search_response import (
    CollectionSearchResponse as CollectionSearchResponse,
)
from kapsula.presentation.api.dto.document_detail_response import (
    DocumentDetailResponse as DocumentDetailResponse,
)
from kapsula.presentation.api.dto.document_export_info import (
    DocumentExportInfo as DocumentExportInfo,
)
from kapsula.presentation.api.dto.document_info import DocumentInfo as DocumentInfo
from kapsula.presentation.api.dto.document_list_item import (
    DocumentListItem as DocumentListItem,
)
from kapsula.presentation.api.dto.document_list_response import (
    DocumentListResponse as DocumentListResponse,
)
from kapsula.presentation.api.dto.intelligent_collection_search_response import (
    IntelligentCollectionSearchResponse as IntelligentCollectionSearchResponse,
)
from kapsula.presentation.api.dto.intelligent_search_response import (
    IntelligentSearchResponse as IntelligentSearchResponse,
)
from kapsula.presentation.api.dto.library_card_info import (
    LibraryCardInfo as LibraryCardInfo,
)
from kapsula.presentation.api.dto.progress_response import (
    ProgressResponse as ProgressResponse,
)
from kapsula.presentation.api.dto.search_plan import SearchPlan as SearchPlan
from kapsula.presentation.api.dto.search_request import (
    SearchRequest as SearchRequest,
)
from kapsula.presentation.api.dto.search_response import (
    SearchResponse as SearchResponse,
)
from kapsula.presentation.api.dto.search_result import SearchResult as SearchResult
from kapsula.presentation.api.dto.streaming_progress_event import (
    StreamingProgressEvent as StreamingProgressEvent,
)
from kapsula.presentation.api.dto.sub_answer import SubAnswer as SubAnswer
from kapsula.presentation.api.dto.upload_request import (
    UploadRequest as UploadRequest,
)
from kapsula.presentation.api.dto.upload_response import (
    UploadResponse as UploadResponse,
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
