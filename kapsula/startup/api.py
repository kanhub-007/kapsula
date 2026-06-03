"""API startup — app factory and uvicorn runner.

Clean architecture: the startup/ layer (composition root) creates the FastAPI
app and wires all dependencies. The presentation/ layer only declares routes.
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kapsula.presentation.api.routes import api_router
from kapsula.startup import bootstrap

load_dotenv()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting Document Chunking API v2.0.0")
    bootstrap()
    yield
    logger.info("Shutting down Document Chunking API")


def create_app() -> FastAPI:
    """Build the FastAPI application with all middleware and routes wired."""
    app = FastAPI(
        title="Document Chunking API",
        description="API for uploading markdown files, extracting structure, and chunking content",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    logger.info("Document Chunking API initialized")
    return app


# Module-level singleton — created once at import time for uvicorn
app = create_app()


def run():
    """Start the uvicorn server. Called by CLI entry points."""
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8001"))
    reload = os.getenv("API_RELOAD", "").lower() in ("1", "true", "yes")

    uvicorn.run(
        "kapsula.startup.api:app",
        host=host,
        port=port,
        reload=reload,
    )
