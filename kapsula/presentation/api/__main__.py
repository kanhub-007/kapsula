"""CLI entry point — delegates to the startup layer.

Usage: python -m kapsula.presentation.api
"""

import logging

from kapsula.startup.api import run

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

if __name__ == "__main__":
    run()
