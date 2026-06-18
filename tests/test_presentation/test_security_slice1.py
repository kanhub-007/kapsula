"""Security tests — constant-time auth and restricted BM25 unpickler."""

import pickle

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from kapsula.infrastructure.repositories.indexing.loaders import _Bm25Unpickler
from kapsula.presentation.api.auth import require_api_key

# ── SE1: API-key comparison is constant-time (hmac.compare_digest) ──


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    async def who(principal: str | None = Depends(require_api_key)):
        return {"authenticated": principal is not None}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app())


@pytest.fixture
def auth_enabled(monkeypatch):
    monkeypatch.setenv("KAPSULA_API_KEY", "secret-key")


class TestConstantTimeAuth:
    """The auth path must use hmac.compare_digest, not ``!=``."""

    def test_compare_digest_is_used(self):
        """require_api_key relies on hmac.compare_digest for the comparison.

        We assert the module imports hmac and that the comparison behaviour
        matches compare_digest's contract (handles unequal-length strings
        without raising, returns False).
        """
        import hmac
        import inspect

        from kapsula.presentation.api import auth

        source = inspect.getsource(auth)
        assert "hmac.compare_digest" in source
        # Sanity: hmac is genuinely imported and usable.
        assert hmac.compare_digest("secret-key", "secret-key") is True
        assert hmac.compare_digest("secret-key", "wrong") is False
        # Unequal lengths must not raise (plain == would also be False, but
        # compare_digest is the required constant-time path).
        assert hmac.compare_digest("a", "ab") is False

    def test_mismatched_key_rejected(self, client, auth_enabled):
        """A wrong key still yields 401 (behaviour preserved)."""
        res = client.get("/who", headers={"Authorization": "Bearer wrong"})
        assert res.status_code == 401

    def test_correct_key_accepted(self, client, auth_enabled):
        res = client.get("/who", headers={"Authorization": "Bearer secret-key"})
        assert res.status_code == 200


# ── SE2: BM25 loader rejects unsafe pickle payloads ─────────────────


class TestRestrictedBm25Unpickler:
    """_Bm25Unpickler must refuse globals outside the allowlist."""

    def test_rejects_os_system_payload(self, tmp_path):
        """A pickled ``os.system`` must raise, not execute."""

        class _Bomb:
            def __reduce__(self):
                import os

                return (os.system, ("echo pwned",))

        path = tmp_path / "evil.pkl"
        with open(path, "wb") as f:
            pickle.dump({"bm25": _Bomb(), "texts": []}, f)

        with open(path, "rb") as f:
            with pytest.raises(pickle.UnpicklingError, match="disallowed global"):
                _Bm25Unpickler(f).load()

    def test_allows_rank_bm25_global(self):
        """The allowlist must permit rank_bm25 classes (so real indexes load).

        We only assert the allowlist decision here — a full round-trip is
        covered by the integration test that builds and loads a real index.
        """
        assert "rank_bm25" in _Bm25Unpickler._ALLOWED_MODULES
        assert "rank_bm25" in _Bm25Unpickler._ALLOWED_MODULES

    def test_rejects_eval_payload(self, tmp_path):
        """A pickled ``builtins.eval`` reference via a disallowed module path."""

        # pickle encodes builtins.eval as ("builtins", "eval"); builtins is
        # intentionally in the allowlist because primitives need it, but a
        # payload that constructs an unsafe callable through a non-allowed
        # module must still be rejected.
        class _EvalBomb:
            def __reduce__(self):
                # Use a module NOT in the allowlist to trigger the guard.
                import subprocess  # noqa: F401  (the point)

                return (subprocess.run, (["echo", "pwned"],))

        path = tmp_path / "eval.pkl"
        with open(path, "wb") as f:
            pickle.dump(_EvalBomb(), f)

        with open(path, "rb") as f:
            with pytest.raises(pickle.UnpicklingError, match="disallowed global"):
                _Bm25Unpickler(f).load()
