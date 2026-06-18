"""API-key authentication dependency.

Auth is OFF by default (preserves existing local/development usage) and turns
ON automatically when ``KAPSULA_API_KEY`` is set in the environment. When on,
every request must carry it either as ``Authorization: Bearer <key>`` or as
the ``X-API-Key`` query/header. Requests without a matching key get 401.

This closes the \"unauthenticated network-exposed API\" gap. Account-scoped
authorization (IDOR prevention) is a follow-up: it requires routing every read
through the authenticated account, which is a larger, spec-driven change.
"""

import os

from fastapi import Header, HTTPException, Query, status


def _configured_key() -> str | None:
    """Return the API key configured via env, or None when auth is disabled."""
    return os.getenv("KAPSULA_API_KEY") or None


async def require_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key_query: str | None = Query(default=None, alias="api_key"),
) -> str | None:
    """FastAPI dependency: enforce the configured API key, if any.

    Returns the principal identifier (the key) for downstream use, or None
    when auth is disabled (no key configured).
    """
    expected = _configured_key()
    if expected is None:
        # Auth disabled — local/development mode.
        return None

    presented = x_api_key or api_key_query
    if not presented and authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            presented = parts[1].strip()

    if not presented or presented != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": 'Bearer realm="kapsula"'},
        )
    return presented
