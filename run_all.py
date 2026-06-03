"""Run both API and MCP servers concurrently — python run_all.py

API  → http://localhost:8001/docs
MCP  → http://localhost:8002      (HTTP transport)
"""

import os
import sys
import threading
import time

# Force HTTP transport for MCP when running both
os.environ.setdefault("KAPSULA_TRANSPORT", "http")
os.environ.setdefault("KAPSULA_HOST", "127.0.0.1")
os.environ.setdefault("KAPSULA_PORT", "8002")


def main():
    from kapsula.startup.api import run as run_api
    from kapsula.startup.mcp import run as run_mcp

    # Start MCP in a background thread
    mcp_thread = threading.Thread(target=run_mcp, daemon=True, name="mcp-server")
    mcp_thread.start()
    time.sleep(1)  # let MCP bootstrap before API takes over

    print("API  → http://localhost:8001/docs")
    print("MCP  → http://localhost:8002")
    print()

    # Run API in the main thread (uvicorn blocks)
    run_api()


if __name__ == "__main__":
    main()
