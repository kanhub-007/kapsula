"""Health check routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def root():
    """API health check endpoint."""
    return {
        "message": "Kapsula Memory System API is running",
        "version": "1.0.0",
        "docs": "/docs",
        "service": "kapsula-memory-system",
    }


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "kapsula-memory-system"}
