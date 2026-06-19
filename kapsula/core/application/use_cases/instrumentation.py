"""Small instrumentation helpers for application use cases."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from time import perf_counter, sleep
from typing import TypeVar

T = TypeVar("T")


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


# ---------------------------------------------------------------------------
# Best-effort phase / retry decorators (closes M6).
#
# These wrap the repeated ``try: ... except Exception as exc: log; fallback``
# boilerplate that appeared ~50× across use cases. They narrow the contract:
#  - ``best_effort_phase`` is for OPTIONAL steps (one sub-doc search, one LLM
#    call) where a failure must not abort the whole operation.
#  - ``retry_on_transient`` is for network calls that may flake.
# Both log the real exception server-side and NEVER leak it to the caller
# except via the documented fallback.
# ---------------------------------------------------------------------------


def best_effort_phase(
    fallback=None,
    *,
    log_message: str = "phase failed",
    logger=None,
):
    """Decorator: log and swallow exceptions, returning *fallback*.

    Use ONLY for genuinely optional pipeline phases (e.g. enriching one
    card, routing one sub-document). Do NOT use to mask programming bugs in
    mandatory logic — narrow the exception type there instead.

    Args:
        fallback: Value returned on failure (default ``None``). For async
            functions returning a coroutine this still returns the sync value.
        log_message: Human-readable label logged with the exception.
        logger: Logger-like object; defaults to a module logger named after
            the wrapped function's module.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        log = logger or _logger_for(func)

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — best-effort by design
                log.exception("%s: %s", log_message, exc)
                return fallback

        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            try:
                return await func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — best-effort by design
                log.exception("%s: %s", log_message, exc)
                return fallback

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper

    return decorator


def retry_on_transient(
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 0.5,
    exceptions=(Exception,),
    logger=None,
):
    """Decorator: retry a call on transient exceptions with linear backoff.

    Args:
        max_attempts: Total attempts (including the first).
        backoff_seconds: Sleep before attempt N is ``backoff_seconds * (N-1)``.
        exceptions: Exception tuple that triggers a retry; others propagate.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        log = logger or _logger_for(func)

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    delay = backoff_seconds * attempt
                    log.warning(
                        "%s attempt %s/%s failed: %s; retrying in %.2fs",
                        func.__name__,
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )
                    sleep(delay)
            if last_exc is None:  # pragma: no cover — loop always sets it before here
                raise RuntimeError("retry loop exited without an exception")
            raise last_exc

        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:

            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    delay = backoff_seconds * attempt
                    log.warning(
                        "%s attempt %s/%s failed: %s; retrying in %.2fs",
                        func.__name__,
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
            if last_exc is None:  # pragma: no cover — loop always sets it before here
                raise RuntimeError("retry loop exited without an exception")
            raise last_exc

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper

    return decorator


def _logger_for(func: Callable[..., ...]):
    """Return a logger named after *func*'s module."""
    module = getattr(func, "__module__", __name__) or __name__
    return logging.getLogger(module)
