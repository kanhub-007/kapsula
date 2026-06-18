"""Small instrumentation helpers for application use cases."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Iterator


@dataclass
class Timing:
    """Elapsed-time holder yielded by ``log_timing`` context manager."""

    elapsed: float = 0.0


@contextmanager
def log_timing(logger, message: str, **fields) -> Iterator[Timing]:
    """Log elapsed time for an operation.

    Args:
        logger: Logger-like object with ``info``.
        message: Human-readable operation label.
        **fields: Extra fields logged as key=value pairs.
    """
    timing = Timing()
    started = perf_counter()
    try:
        yield timing
    finally:
        timing.elapsed = perf_counter() - started
        suffix = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.info(
            "%s completed in %.3fs%s",
            message,
            timing.elapsed,
            f" ({suffix})" if suffix else "",
        )
