"""API startup — app factory and uvicorn runner.

Clean architecture: the startup/ layer (composition root) creates the FastAPI
app and wires all dependencies. The presentation/ layer only declares routes.
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kapsula.presentation.api.auth import require_api_key
from kapsula.presentation.api.routes import api_router
from kapsula.startup import bootstrap

load_dotenv()

logger = logging.getLogger(__name__)


def _cors_origins() -> list[str]:
    """Return the configured CORS allowlist.

    Reads ``KAPSULA_CORS_ORIGINS`` (comma-separated). Defaults to loopback
    only — never the insecure ``*`` wildcard.
    """
    raw = os.getenv("KAPSULA_CORS_ORIGINS", "http://127.0.0.1,http://localhost")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


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

    # CORS: explicit allowlist only. Credentials are enabled only when an
    # origin allowlist is configured (never together with a wildcard).
    origins = _cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=bool(origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API-key auth gate applied to every route. Disabled (no-op) unless
    # KAPSULA_API_KEY is set, preserving local/development usage.
    if os.getenv("KAPSULA_API_KEY"):
        logger.info("API-key authentication ENABLED (KAPSULA_API_KEY set)")
        api_router.dependencies = list(api_router.dependencies) + [
            Depends(require_api_key)
        ]
    else:
        logger.warning(
            "KAPSULA_API_KEY not set — API is UNAUTHENTICATED. "
            "Set it before exposing the API beyond loopback."
        )

    app.include_router(api_router)
    logger.info("Document Chunking API initialized")
    return app


# Module-level singleton — created once at import time for uvicorn
app = create_app()


def run():
    """Start the uvicorn server. Called by CLI entry points."""
    import uvicorn

    # Default to loopback only. Bind 0.0.0.0 only if explicitly requested,
    # and ensure auth is enabled before doing so.
    host = os.getenv("API_HOST", "127.0.0.1")
    if host in ("0.0.0.0", "::") and not os.getenv("KAPSULA_API_KEY"):
        raise RuntimeError(
            "Refusing to bind " + host + " without KAPSULA_API_KEY set. "
            "Configure authentication before exposing the API publicly."
        )
    port = int(os.getenv("API_PORT", "8001"))
    reload = os.getenv("API_RELOAD", "").lower() in ("1", "true", "yes")

    uvicorn.run(
        "kapsula.startup.api:app",
        host=host,
        port=port,
        reload=reload,
    )
