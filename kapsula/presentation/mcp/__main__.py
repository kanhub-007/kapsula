"""CLI entry point — delegates to the startup layer.

Usage:
    python -m kapsula.presentation.mcp

Environment variables:
    KAPSULA_TRANSPORT  Transport mode: "stdio" (default) or "http"
    KAPSULA_HOST       HTTP host (default: 127.0.0.1)
    KAPSULA_PORT       HTTP port (default: 8002)
    HF_TOKEN             HuggingFace API token for LLM/embedding features
"""

import logging

from kapsula.startup.mcp import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

if __name__ == "__main__":
    run()
