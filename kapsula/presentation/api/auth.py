"""API-key authentication dependency.

Auth is OFF by default (preserves existing local/development usage) and turns
ON automatically when ``KAPSULA_API_KEY`` is set in the environment. When on,
every request must carry it either as ``Authorization: Bearer <key>`` or as
the ``X-API-Key`` query/header. Requests without a matching key get 401.

Comparison uses :func:`hmac.compare_digest` (constant-time) to avoid leaking
the key via a timing side-channel under sustained probing.

This closes the "unauthenticated network-exposed API" gap.

**Authorization model (per the 2026-06-18 IDOR decision, see
``specs/2026-06-18_account-scoped-authorization/``):** kapsula is single-tenant.
Accounts are organizational units (the Account → Collection → Document
hierarchy), not security boundaries — the operator may use multiple accounts,
all trusted to the one deployment principal. There is no inter-account
isolation to enforce, so this dependency is the complete authn/authz story.
If a future deployment hosts mutually-distrusting parties on one process,
add a ``PrincipalResolver`` + per-resource ownership checks at that point.
"""

import hmac
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

    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": 'Bearer realm="kapsula"'},
        )
    return presented
