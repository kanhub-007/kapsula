"""Small HTTP helpers shared by API route modules."""

import re
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, Request, status

# Header-injection / response-splitting defence: drop CR, LF, double-quote,
# and any control character from a user-supplied name used in a header.
_HEADER_UNSAFE = re.compile(r"[\r\n\"\x00-\x1f\x7f]")


def client_ip(request: Request) -> str:
    """Return the client IP, or ``"unknown"`` when unavailable.

    ``request.client`` is ``None`` behind some proxies, test transports,
    and unix sockets — reading ``request.client.host`` directly raises
    ``AttributeError`` in those cases.
    """
    return request.client.host if request.client else "unknown"


def safe_attachment_filename(name: str, fallback: str = "download") -> str:
    """Return a header-safe filename for ``Content-Disposition``.

    User-controlled names (collection names, uploaded filenames) flow into
    the ``Content-Disposition`` response header. Without sanitisation an
    attacker can inject ``\r\n`` (HTTP response splitting) or embedded
    double-quotes / script content (stored XSS via download).

    Strips CR/LF, control chars, and quotes; collapses whitespace; falls
    back to *fallback* when nothing usable remains.
    """
    if not name:
        return fallback
    cleaned = _HEADER_UNSAFE.sub(" ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Trim to a reasonable length to keep headers manageable.
    cleaned = cleaned[:128].strip()
    return cleaned or fallback


def content_disposition_attachment(filename: str) -> str:
    """Build a sanitised ``Content-Disposition: attachment`` header value.

    Uses the RFC 6266 ``filename*`` form (percent-encoded UTF-8) which is
    safe for any Unicode name, plus an ASCII ``filename`` fallback for
    older clients. Both come from :func:`safe_attachment_filename` so they
    are guaranteed header-safe.
    """
    safe = safe_attachment_filename(filename)
    quoted = quote(safe, safe="")
    return f"attachment; filename=\"{safe}\"; filename*=UTF-8''{quoted}"


def internal_server_error(detail: str = "Internal server error") -> HTTPException:
    """Return a generic 500 with no internal detail leak.

    Route handlers must NOT forward ``str(exc)`` to the client — it can
    expose file paths, SQL fragments, library internals, or stack detail.
    Log the real exception server-side and return this generic error.
    """
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail
    )


def safe_document_filename(original: str, suffix: str) -> str:
    """Build a sanitised download filename from an uploaded document name.

    Replaces the document's ``.md`` extension with *suffix* (e.g.
    ``"_structure.md"``) and strips header-unsafe characters.
    """
    stem = Path(original or "document").stem or "document"
    return safe_attachment_filename(f"{stem}{suffix}", fallback=f"document{suffix}")
