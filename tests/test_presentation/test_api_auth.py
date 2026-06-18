"""Tests for the API-key auth dependency (C3).

Black-box: exercises the documented contract — disabled when no key is
configured, enforces Bearer / X-API-Key / query param when configured, rejects
mismatches with 401. Uses FastAPI's TestClient against a tiny app, no mocks.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from kapsula.presentation.api.auth import require_api_key


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    async def who(principal: str | None = Depends(require_api_key)):
        return {"authenticated": principal is not None}

    return app


@pytest.fixture
def app() -> FastAPI:
    return _build_app()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_enabled(monkeypatch):
    monkeypatch.setenv("KAPSULA_API_KEY", "secret-key")


@pytest.fixture
def auth_disabled(monkeypatch):
    monkeypatch.delenv("KAPSULA_API_KEY", raising=False)


class TestRequireApiKey:
    """Contract tests for require_api_key."""

    def test_disabled_when_no_key_configured(self, client, auth_disabled):
        """No KAPSULA_API_KEY -> auth is a no-op, request succeeds unauthenticated."""
        res = client.get("/who")
        assert res.status_code == 200
        assert res.json() == {"authenticated": False}

    def test_bearer_header_accepted(self, client, auth_enabled):
        """Authorization: Bearer <key> is accepted when it matches."""
        res = client.get("/who", headers={"Authorization": "Bearer secret-key"})
        assert res.status_code == 200
        assert res.json() == {"authenticated": True}

    def test_x_api_key_header_accepted(self, client, auth_enabled):
        """X-API-Key header is accepted when it matches."""
        res = client.get("/who", headers={"X-API-Key": "secret-key"})
        assert res.status_code == 200
        assert res.json() == {"authenticated": True}

    def test_query_param_accepted(self, client, auth_enabled):
        """?api_key=<key> is accepted (useful for EventSource/downloads)."""
        res = client.get("/who", params={"api_key": "secret-key"})
        assert res.status_code == 200
        assert res.json() == {"authenticated": True}

    def test_missing_credentials_rejected(self, client, auth_enabled):
        """No credentials at all -> 401."""
        res = client.get("/who")
        assert res.status_code == 401
        assert "api key" in res.json()["detail"].lower()

    def test_wrong_key_rejected(self, client, auth_enabled):
        """A non-matching key -> 401."""
        res = client.get("/who", headers={"X-API-Key": "wrong"})
        assert res.status_code == 401

    def test_malformed_authorization_rejected(self, client, auth_enabled):
        """Authorization header without Bearer scheme -> 401."""
        res = client.get("/who", headers={"Authorization": "secret-key"})
        assert res.status_code == 401

    def test_bearer_with_wrong_token_rejected(self, client, auth_enabled):
        """Bearer with a non-matching token -> 401."""
        res = client.get("/who", headers={"Authorization": "Bearer nope"})
        assert res.status_code == 401
