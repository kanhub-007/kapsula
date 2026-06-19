"""Logo upload validation and storage helper (extracted from collections route).

Single responsibility: validate and persist a user-uploaded collection
logo. Owns the size limit, extension allowlist, and magic-byte content
check so a renamed/oversized/malicious upload is rejected before it touches
disk (closes H3, and pulls the logo concern out of the route handler to
keep the route file focused).
"""

import os
from pathlib import Path

from fastapi import HTTPException, UploadFile

# Allowed image extensions. SVG is intentionally excluded: user-supplied
# SVG can carry <script>/event handlers and is served back to browsers as
# stored XSS. Add SVG only behind a dedicated sanitiser if needed.
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# Hard cap on logo upload size. Logos are small brand images; a request
# larger than this is almost certainly abuse (disk/memory exhaustion DoS)
# or a misconfigured client.
MAX_LOGO_BYTES = 5 * 1024 * 1024  # 5 MiB


def logos_dir(data_dir: str) -> str:
    """Return (and create) the logos directory under *data_dir*."""
    directory = os.path.join(data_dir, "logos")
    os.makedirs(directory, exist_ok=True)
    return directory


def _matches_image_magic(data: bytes, ext: str) -> bool:
    """Return True if *data* starts with a known signature for *ext*.

    WebP is confirmed by the trailing ``WEBP`` FourCC inside the RIFF chunk.
    """
    head = data[:16]
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp":
        return head.startswith(b"RIFF") and b"WEBP" in data[:16]
    return False


def save_logo(file: UploadFile, collection_id: str, logos_directory: str) -> str:
    """Validate and save a logo file; return the stored filename.

    Validates extension, size (``MAX_LOGO_BYTES``), and magic bytes so a
    renamed/oversized/malicious upload is rejected before it touches disk.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Logo file has no filename")
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read fully so we can validate size and content. UploadFile is a
    # SpooledTemporaryFile; reading it into memory is bounded by MAX_LOGO_BYTES.
    payload = file.file.read()
    if len(payload) > MAX_LOGO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Logo too large: {len(payload)} bytes "
                f"(limit {MAX_LOGO_BYTES} bytes)"
            ),
        )
    if not payload:
        raise HTTPException(status_code=400, detail="Logo file is empty")

    # Validate content matches the declared image type (not just the extension).
    if not _matches_image_magic(payload, file_ext):
        raise HTTPException(
            status_code=400,
            detail="File content does not match its declared image type",
        )

    logo_filename = f"{collection_id}{file_ext}"
    logo_path = os.path.join(logos_directory, logo_filename)
    with open(logo_path, "wb") as buffer:
        buffer.write(payload)

    return logo_filename


def media_type_for_logo(filename: str) -> str:
    """Return the media type for a stored logo filename."""
    ext = Path(filename).suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return media_types.get(ext, "application/octet-stream")
