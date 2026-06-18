from fastapi import APIRouter
from .documents import router as documents_router
from .collections import router as collections_router
from .accounts import router as accounts_router
from .health import router as health_router
from .search_collection import router as search_collection_router
from .search_document import router as search_document_router
from .search_intelligent import router as search_intelligent_router

# Create main API router
api_router = APIRouter()

# Include sub-routers
api_router.include_router(health_router, tags=["Health"])
api_router.include_router(accounts_router, prefix="/accounts", tags=["Accounts"])
api_router.include_router(
    collections_router, prefix="/collections", tags=["Collections"]
)
api_router.include_router(documents_router, prefix="/documents", tags=["Documents"])
api_router.include_router(search_collection_router, prefix="/search", tags=["Search"])
api_router.include_router(search_document_router, prefix="/search", tags=["Search"])
api_router.include_router(search_intelligent_router, prefix="/search", tags=["Search"])

__all__ = ["api_router"]
