"""Tests for MCP server foundation — server module."""

import os
from unittest.mock import patch

from kapsula.startup.mcp import create_server, get_transport_config
from kapsula.startup import bootstrap


class TestCreateServer:
    def test_creates_server_with_correct_name(self):
        """Server should be created with the kapsula name."""
        server = create_server()
        assert server is not None
        assert server.name == "kapsula"

    def test_creates_server_with_instructions(self):
        """Server should include usage instructions."""
        server = create_server()
        assert server.instructions is not None
        assert len(server.instructions) > 0

    def test_server_has_tools_registered(self):
        """Server should register tools on creation."""
        server = create_server()
        # FastMCP stores tools internally; verify tools list is populated
        from fastmcp import Client
        import asyncio

        async def _test():
            async with Client(server) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert isinstance(tools, list)
                # We expect at least the search, account, collection tools
                assert len(tools) > 0

        asyncio.run(_test())


class TestBootstrap:
    def test_creates_default_account_on_fresh_db(self):
        """Should create a default 'kapsula' account if none exists."""
        from kapsula.infrastructure.data import SessionLocal, Account

        db = SessionLocal()
        try:
            # Clean up any existing accounts
            db.query(Account).delete()
            db.commit()

            # Bootstrap should create the default account
            bootstrap()

            account = db.query(Account).filter(Account.name == "kapsula").first()
            assert account is not None
            assert account.account_id is not None
            assert len(account.account_id) > 0
        finally:
            db.close()

    def test_skips_account_creation_if_exists(self):
        """Should not create a duplicate account if one already exists."""
        from kapsula.infrastructure.data import SessionLocal, Account

        db = SessionLocal()
        try:
            # Clean and create one
            db.query(Account).delete()
            db.commit()
            bootstrap()

            count_before = (
                db.query(Account).filter(Account.name == "kapsula").count()
            )

            # Bootstrap again
            bootstrap()

            count_after = db.query(Account).filter(Account.name == "kapsula").count()
            assert count_before == count_after == 1
        finally:
            db.close()


class TestTransportSelection:
    def test_default_transport_is_stdio(self):
        """Without KAPSULA_TRANSPORT env var, transport should default to stdio."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KAPSULA_TRANSPORT", None)
            config = get_transport_config()
            assert config["transport"] == "stdio"

    def test_http_transport_when_configured(self):
        """When KAPSULA_TRANSPORT=http, should return http config."""
        with patch.dict(os.environ, {"KAPSULA_TRANSPORT": "http"}):
            config = get_transport_config()
            assert config["transport"] == "http"
            assert config["host"] == "127.0.0.1"
            assert config["port"] == 8002

    def test_custom_host_and_port(self):
        """Should respect custom host and port env vars."""
        with patch.dict(
            os.environ,
            {
                "KAPSULA_TRANSPORT": "http",
                "KAPSULA_HOST": "0.0.0.0",
                "KAPSULA_PORT": "9000",
            },
        ):
            config = get_transport_config()
            assert config["host"] == "0.0.0.0"
            assert config["port"] == 9000
