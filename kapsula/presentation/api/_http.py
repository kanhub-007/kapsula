"""Small HTTP helpers shared by API route modules."""

from fastapi import Request


def client_ip(request: Request) -> str:
    """Return the client IP, or ``"unknown"`` when unavailable.

    ``request.client`` is ``None`` behind some proxies, test transports,
    and unix sockets — reading ``request.client.host`` directly raises
    ``AttributeError`` in those cases.
    """
    return request.client.host if request.client else "unknown"
