"""Tests for presentation HTTP helpers (closes H5 + H1/H3 regression guards).

Black-box: the filename sanitiser must defeat header-injection / response
splitting, and the generic 500 factory must never leak internal detail.
"""

from fastapi import HTTPException

from kapsula.presentation.api._http import (
    content_disposition_attachment,
    internal_server_error,
    safe_attachment_filename,
    safe_document_filename,
)


class TestSafeAttachmentFilename:
    def test_strips_crlf_to_prevent_response_splitting(self):
        out = safe_attachment_filename("evil\r\nX-Injected: yes")
        # The security contract: no CR/LF means the value cannot start a new
        # header line (response splitting). The literal text "X-Injected"
        # remaining as a filename fragment is harmless.
        assert "\r" not in out
        assert "\n" not in out

    def test_strips_embedded_double_quotes(self):
        # Embedded quotes could break out of the quoted filename segment.
        out = safe_attachment_filename('a"; <script>alert(1)</script>; x="')
        assert '"' not in out

    def test_strips_control_characters(self):
        out = safe_attachment_filename("name\x00\x01\x7f")
        for ch in ("\x00", "\x01", "\x7f"):
            assert ch not in out

    def test_empty_returns_fallback(self):
        assert safe_attachment_filename("") == "download"
        assert safe_attachment_filename("   ") == "download"
        assert safe_attachment_filename("", fallback="logo") == "logo"

    def test_truncates_overlong_names(self):
        out = safe_attachment_filename("x" * 500)
        assert len(out) <= 128

    def test_normal_whitespace_collapsed(self):
        assert safe_attachment_filename("a   b\tc") == "a b c"


class TestContentDispositionAttachment:
    def _parse(self, header: str) -> tuple[str, str]:
        # Returns (ascii_filename, filename_star)
        ascii_part = header.split('filename="')[1].split('"')[0]
        star_part = header.split("filename*=UTF-8''")[1]
        return ascii_part, star_part

    def test_contains_both_ascii_and_utf8_forms(self):
        header = content_disposition_attachment("résumé.md")
        ascii_name, star = self._parse(header)
        # ASCII form has the raw (sanitised) name; star form is percent-encoded.
        assert "r" in ascii_name
        assert "sum" in ascii_name
        assert "%C3%A9" in star  # é percent-encoded in UTF-8

    def test_user_controlled_name_is_sanitised(self):
        header = content_disposition_attachment("a\r\nb")
        assert "\r" not in header
        assert "\n" not in header


class TestSafeDocumentFilename:
    def test_replaces_md_extension_with_suffix(self):
        assert safe_document_filename("notes.md", "_structure.md") == (
            "notes_structure.md"
        )

    def test_handles_missing_extension(self):
        assert safe_document_filename("README", "_chunks.json") == (
            "README_chunks.json"
        )

    def test_sanitises_user_controlled_stem(self):
        out = safe_document_filename("ev\r\nil.md", "_structure.md")
        assert "\r" not in out
        assert "\n" not in out


class TestInternalServerError:
    def test_returns_500(self):
        exc = internal_server_error()
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 500

    def test_default_detail_is_generic(self):
        exc = internal_server_error()
        assert exc.detail == "Internal server error"

    def test_custom_detail(self):
        exc = internal_server_error("Search failed")
        assert exc.detail == "Search failed"
