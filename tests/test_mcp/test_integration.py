"""Integration tests for MCP server — tool execution, caching, and async safety."""

import os
import asyncio
import pytest
from unittest.mock import patch, MagicMock


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def setup_db():
    """Ensure DB tables exist and default account is created."""
    from doc_search.infrastructure.data.connection import init_db
    from doc_search.startup import bootstrap
    init_db()
    bootstrap()
    yield


@pytest.fixture
def clean_cache():
    """Clear the singleton cache before and after each test."""
    from doc_search.presentation.mcp.tools import _clear_cache
    _clear_cache()
    yield
    _clear_cache()


@pytest.fixture
def mock_hf_token():
    """Ensure HF_TOKEN is set (to a fake value) for tests that need it."""
    with patch.dict(os.environ, {"HF_TOKEN": "fake-token-for-testing"}, clear=False):
        yield


# ── Protocol handshake tests ────────────────────────────────────


class TestMCPHandshake:
    def test_initialize_handshake(self, clean_cache):
        """Server should respond to MCP initialize request."""
        from fastmcp import Client
        from doc_search.startup.mcp import create_server

        server = create_server()

        async def _test():
            async with Client(server) as client:
                result = await client.initialize()
                assert result is not None
                assert result.serverInfo.name == "doc-search"

        asyncio.run(_test())

    def test_list_tools_returns_registered_tools(self, clean_cache):
        """Tools list should include all registered tools."""
        from fastmcp import Client
        from doc_search.startup.mcp import create_server

        server = create_server()

        async def _test():
            async with Client(server) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert isinstance(tools, list)
                assert len(tools) > 0

                tool_names = {t.name for t in tools}
                # Core tools that should always be registered
                assert "create_account" in tool_names
                assert "list_accounts" in tool_names
                assert "create_collection" in tool_names
                assert "list_collections" in tool_names
                assert "search_documents" in tool_names
                assert "intelligent_search" in tool_names

        asyncio.run(_test())


# ── Singleton caching tests ─────────────────────────────────────


class TestSingletonCaching:
    def test_chat_client_is_cached(self, clean_cache):
        """Calling _get_chat_client() multiple times returns the same instance."""
        from doc_search.presentation.mcp.tools import _get_chat_client, _clear_cache

        _clear_cache()
        c1 = _get_chat_client()
        c2 = _get_chat_client()
        assert c1 is c2

    def test_embedder_is_cached(self, clean_cache):
        """HuggingFaceEmbedder should be a singleton — avoids re-init of InferenceClient."""
        from doc_search.presentation.mcp.tools import _get_embedder, _clear_cache

        _clear_cache()
        e1 = _get_embedder()
        e2 = _get_embedder()
        assert e1 is e2

    def test_reranker_is_cached(self, clean_cache):
        """LocalCrossEncoderReranker should be a singleton — model loaded once."""
        from doc_search.presentation.mcp.tools import _get_reranker, _clear_cache

        _clear_cache()
        r1 = _get_reranker()
        r2 = _get_reranker()
        assert r1 is r2

    def test_intelligent_searcher_is_cached(self, clean_cache):
        """Calling _get_intelligent_searcher() multiple times returns the same instance."""
        from doc_search.presentation.mcp.tools import _get_intelligent_searcher, _clear_cache

        _clear_cache()
        s1 = _get_intelligent_searcher()
        s2 = _get_intelligent_searcher()
        assert s1 is s2

    def test_query_planner_is_cached(self, clean_cache):
        """Calling _get_query_planner() multiple times returns the same instance."""
        from doc_search.presentation.mcp.tools import _get_query_planner, _clear_cache

        _clear_cache()
        p1 = _get_query_planner()
        p2 = _get_query_planner()
        assert p1 is p2

    def test_clear_cache_resets_all(self, clean_cache):
        """After clearing cache, new instances are created for all 5 singletons."""
        from doc_search.presentation.mcp.tools import (
            _get_chat_client, _get_embedder, _get_reranker,
            _get_query_planner, _get_intelligent_searcher, _clear_cache,
        )

        _clear_cache()
        c1 = _get_chat_client()
        e1 = _get_embedder()
        r1 = _get_reranker()
        p1 = _get_query_planner()
        s1 = _get_intelligent_searcher()

        _clear_cache()
        c2 = _get_chat_client()
        e2 = _get_embedder()
        r2 = _get_reranker()
        p2 = _get_query_planner()
        s2 = _get_intelligent_searcher()

        assert c1 is not c2
        assert e1 is not e2
        assert r1 is not r2
        assert p1 is not p2
        assert s1 is not s2

    def test_multi_index_searcher_reuses_cached_deps(self, clean_cache, mock_hf_token):
        """_get_multi_index_searcher should pass cached singletons to the searcher."""
        from doc_search.presentation.mcp.tools import (
            _get_multi_index_searcher, _get_embedder,
            _get_reranker, _get_chat_client, _clear_cache,
        )
        from doc_search.presentation.mcp.db import get_db_session

        _clear_cache()

        with get_db_session() as db:
            searcher = _get_multi_index_searcher(db)
            # The searcher should be using the cached singletons
            assert searcher._embedder is _get_embedder()
            assert searcher._reranker is _get_reranker()
            assert searcher._chat_client is _get_chat_client()


# ── Account / Collection CRUD tests (no HF_TOKEN needed) ────────


class TestAccountTools:
    def test_create_and_list_accounts(self, clean_cache):
        """Create an account and verify it appears in list."""
        from fastmcp import Client
        from doc_search.startup.mcp import create_server

        server = create_server()

        async def _test():
            async with Client(server) as client:
                await client.initialize()

                # List initially — should have default account
                result = await client.call_tool("list_accounts", {})
                assert "doc-search" in result.content[0].text

                # Create a new account
                result = await client.call_tool("create_account", {"name": "test-account"})
                text = result.content[0].text
                assert "test-account" in text
                assert "account_id" in text

                # List again — should include new account
                result = await client.call_tool("list_accounts", {})
                text = result.content[0].text
                assert "test-account" in text

        asyncio.run(_test())

    def test_get_account_details(self, clean_cache):
        """Get account should return details including collections."""
        from fastmcp import Client
        from doc_search.startup.mcp import create_server

        server = create_server()

        async def _test():
            async with Client(server) as client:
                await client.initialize()

                # First get the default account ID
                result = await client.call_tool("list_accounts", {})
                text = result.content[0].text
                # Extract account_id from text like "... — <uuid>"
                lines = text.split("\n")
                account_line = [l for l in lines if "doc-search" in l][0]
                account_id = account_line.split("—")[-1].strip().split()[0]

                result = await client.call_tool("get_account", {"account_id": account_id})
                text = result.content[0].text
                assert "doc-search" in text
                assert account_id in text
                assert "Collections" in text

        asyncio.run(_test())


class TestCollectionTools:
    def test_create_and_list_collections(self, clean_cache):
        """Create a collection and verify it appears."""
        from fastmcp import Client
        from doc_search.startup.mcp import create_server

        server = create_server()

        async def _test():
            async with Client(server) as client:
                await client.initialize()

                result = await client.call_tool("create_collection", {"name": "test-collection"})
                text = result.content[0].text
                assert "test-collection" in text
                assert "collection_id" in text

                result = await client.call_tool("list_collections", {})
                text = result.content[0].text
                assert "test-collection" in text

        asyncio.run(_test())

    def test_get_collection_details(self, clean_cache):
        """Get collection should return details and document count."""
        from fastmcp import Client
        from doc_search.startup.mcp import create_server

        server = create_server()

        async def _test():
            async with Client(server) as client:
                await client.initialize()

                # Create collection
                result = await client.call_tool("create_collection", {"name": "detail-test"})
                text = result.content[0].text
                collection_id = text.split("collection_id: ")[1].strip()

                # Get its details
                result = await client.call_tool("get_collection", {"collection_id": collection_id})
                text = result.content[0].text
                assert "detail-test" in text
                assert "Documents: 0" in text

        asyncio.run(_test())

    def test_create_collection_with_account(self, clean_cache):
        """Create a collection tied to a specific account."""
        from fastmcp import Client
        from doc_search.startup.mcp import create_server

        server = create_server()

        async def _test():
            async with Client(server) as client:
                await client.initialize()

                # Get default account ID
                result = await client.call_tool("list_accounts", {})
                text = result.content[0].text
                lines = text.split("\n")
                account_line = [l for l in lines if "doc-search" in l][0]
                account_id = account_line.split("—")[-1].strip().split()[0]

                result = await client.call_tool(
                    "create_collection",
                    {"name": "accounted-collection", "account_id": account_id}
                )
                text = result.content[0].text
                assert "accounted-collection" in text
                assert "doc-search" in text

        asyncio.run(_test())


# ── Search tool tests (with mocks) ──────────────────────────────


class TestSearchTools:
    def test_search_documents_errors_without_hf_token(self, clean_cache):
        """search_documents raises ToolError when HF_TOKEN is missing."""
        from fastmcp import Client
        from fastmcp.exceptions import ToolError
        from doc_search.startup.mcp import create_server

        # Clear HF_TOKEN so embedder creation fails
        with patch.dict(os.environ, {}, clear=True):
            server = create_server()

            async def _test():
                async with Client(server) as client:
                    await client.initialize()
                    # The embedder requires a token — this should raise ToolError
                    with pytest.raises(ToolError):
                        await client.call_tool("search_documents", {"query": "test"})

            asyncio.run(_test())

    def test_intelligent_search_returns_error_without_hf_token(self, clean_cache):
        """intelligent_search should return an error when HF_TOKEN is not set."""
        with patch.dict(os.environ, {}, clear=True):
            from fastmcp import Client
            from doc_search.startup.mcp import create_server

            server = create_server()

            async def _test():
                async with Client(server) as client:
                    await client.initialize()
                    result = await client.call_tool("intelligent_search", {"query": "test"})
                    text = result.content[0].text
                    assert "HF_TOKEN not set" in text

            asyncio.run(_test())

    def test_search_tools_are_async_safe(self, clean_cache, mock_hf_token):
        """Verify that search tools do not block the event loop.

        This test runs multiple concurrent tool calls and verifies
        they complete within a reasonable timeout, proving that sync
        operations are properly offloaded to thread pools.
        """
        from fastmcp import Client
        from doc_search.startup.mcp import create_server

        server = create_server()

        async def _run_search():
            async with Client(server) as client:
                await client.initialize()
                # Call a lightweight search — even with no collections
                # it should return quickly, not hang
                result = await client.call_tool("search_documents", {"query": "test", "top_k": 3})
                return result.content[0].text

        async def _test():
            # Run multiple searches concurrently — should not deadlock
            tasks = [_run_search() for _ in range(3)]
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=10.0  # 10 sec timeout — if it hangs, test fails
            )
            for r in results:
                if isinstance(r, Exception):
                    pytest.fail(f"Search raised exception: {r}")
                assert isinstance(r, str)

        asyncio.run(_test())


# ── Document upload test (no HF_TOKEN needed for validation) ────


class TestDocumentTools:
    def test_upload_nonexistent_file(self, clean_cache):
        """Uploading a non-existent file should return an error."""
        from fastmcp import Client
        from doc_search.startup.mcp import create_server

        server = create_server()

        async def _test():
            async with Client(server) as client:
                await client.initialize()

                result = await client.call_tool(
                    "upload_document",
                    {"file_path": "/nonexistent/file.md", "collection_id": "fake-id"}
                )
                text = result.content[0].text
                assert "not found" in text.lower()

        asyncio.run(_test())

    def test_list_documents_returns_list(self, clean_cache):
        """Listing documents should return a valid list (may contain existing data)."""
        from fastmcp import Client
        from doc_search.startup.mcp import create_server

        server = create_server()

        async def _test():
            async with Client(server) as client:
                await client.initialize()
                result = await client.call_tool("list_documents", {})
                text = result.content[0].text
                # Should return either "No documents" or a document listing
                assert isinstance(text, str)
                assert len(text) > 0

        asyncio.run(_test())

    def test_list_documents_filter_by_collection(self, clean_cache):
        """Filtering by collection that doesn't exist returns message."""
        from fastmcp import Client
        from doc_search.startup.mcp import create_server

        server = create_server()

        async def _test():
            async with Client(server) as client:
                await client.initialize()
                result = await client.call_tool(
                    "list_documents",
                    {"collection_id": "nonexistent-id"}
                )
                text = result.content[0].text
                assert "not found" in text.lower()

        asyncio.run(_test())
