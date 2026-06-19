"""Tests for the logo upload store (closes H5 + H3 regression guards).

Black-box: the store must reject oversized, empty, wrong-extension, and
content-mismatched uploads before touching disk.
"""

import io

import pytest
from fastapi import HTTPException, UploadFile

from kapsula.presentation.api.logo_store import (
    ALLOWED_EXTENSIONS,
    MAX_LOGO_BYTES,
    media_type_for_logo,
    save_logo,
)


class _FakeUpload(UploadFile):
    """UploadFile stand-in with a readable in-memory payload."""

    def __init__(self, filename: str, payload: bytes):
        self.file = io.BytesIO(payload)
        self.filename = filename


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _jpg_bytes() -> bytes:
    return b"\xff\xd8\xff" + b"\x00" * 32


class TestSaveLogoValidation:
    def test_missing_filename_rejected(self, tmp_path):
        up = _FakeUpload(None, _png_bytes())
        with pytest.raises(HTTPException) as exc:
            save_logo(up, "cid", str(tmp_path))
        assert exc.value.status_code == 400

    def test_wrong_extension_rejected(self, tmp_path):
        up = _FakeUpload("logo.svg", _png_bytes())
        with pytest.raises(HTTPException) as exc:
            save_logo(up, "cid", str(tmp_path))
        assert exc.value.status_code == 400
        assert "svg" not in ALLOWED_EXTENSIONS

    def test_empty_payload_rejected(self, tmp_path):
        up = _FakeUpload("logo.png", b"")
        with pytest.raises(HTTPException) as exc:
            save_logo(up, "cid", str(tmp_path))
        assert exc.value.status_code == 400

    def test_oversized_payload_rejected(self, tmp_path):
        huge = _png_bytes() + b"\x00" * (MAX_LOGO_BYTES + 1)
        up = _FakeUpload("logo.png", huge)
        with pytest.raises(HTTPException) as exc:
            save_logo(up, "cid", str(tmp_path))
        assert exc.value.status_code == 413

    def test_content_mismatch_rejected(self, tmp_path):
        # Declared PNG but the bytes are JPEG.
        up = _FakeUpload("logo.png", _jpg_bytes())
        with pytest.raises(HTTPException) as exc:
            save_logo(up, "cid", str(tmp_path))
        assert exc.value.status_code == 400
        assert "does not match" in exc.value.detail

    def test_valid_png_is_stored_with_collection_id_name(self, tmp_path):
        up = _FakeUpload("brand.png", _png_bytes())
        name = save_logo(up, "cid-123", str(tmp_path))
        assert name == "cid-123.png"
        assert (tmp_path / "cid-123.png").exists()

    def test_valid_jpeg_is_stored(self, tmp_path):
        up = _FakeUpload("brand.jpg", _jpg_bytes())
        name = save_logo(up, "cid-123", str(tmp_path))
        assert name == "cid-123.jpg"


class TestMediaTypeForLogo:
    def test_known_extensions(self):
        assert media_type_for_logo("a.png") == "image/png"
        assert media_type_for_logo("a.jpg") == "image/jpeg"
        assert media_type_for_logo("a.jpeg") == "image/jpeg"
        assert media_type_for_logo("a.gif") == "image/gif"
        assert media_type_for_logo("a.webp") == "image/webp"

    def test_unknown_extension_falls_back(self):
        assert media_type_for_logo("a.bin") == "application/octet-stream"
