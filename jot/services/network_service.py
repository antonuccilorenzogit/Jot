"""
Network connectivity and offline error classification service.
"""

from __future__ import annotations

import os
import socket
import sys
from typing import Final

GEMINI_API_HOST: Final[str] = "generativelanguage.googleapis.com"
GEMINI_API_PORT: Final[int] = 443
DEFAULT_CONNECTIVITY_TIMEOUT: Final[float] = 2.5

_NETWORK_ERROR_MARKERS: Final[tuple[str, ...]] = (
    "getaddrinfo failed",
    "connecterror",
    "connection refused",
    "connection reset",
    "connection aborted",
    "network is unreachable",
    "network unreachable",
    "name or service not known",
    "temporary failure in name resolution",
    "nodename nor servname provided",
    "enotfound",
    "econnrefused",
    "wsaenetunreach",
    "wsahost_not_found",
    "wsaetimedout",
    "wsaeconnrefused",
    "wsaeconnreset",
    "errno 11001",
    "errno 10051",
    "errno 10054",
    "errno 10060",
    "errno 10061",
)


def check_connectivity(
    host: str = GEMINI_API_HOST,
    port: int = GEMINI_API_PORT,
    timeout: float = DEFAULT_CONNECTIVITY_TIMEOUT,
    bypass_in_test: bool = True,
) -> bool:
    """Fast check if the Gemini API endpoint is reachable via TCP.

    Returns True if connection succeeded, False if unreachable or timed out.
    Automatically bypassed in pytest / testing environment unless bypass_in_test=False.
    """
    if bypass_in_test and (
        "pytest" in sys.modules or os.environ.get("JOT_TESTING") == "1"
    ):
        return True

    sock: socket.socket | None = None
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def is_network_online(
    host: str = GEMINI_API_HOST,
    port: int = GEMINI_API_PORT,
    timeout: float = DEFAULT_CONNECTIVITY_TIMEOUT,
) -> bool:
    """Return True if connection to Gemini endpoint succeeds."""
    return check_connectivity(
        host=host, port=port, timeout=timeout, bypass_in_test=False
    )


def is_network_offline_error(exc: Exception | None) -> bool:
    """Return True if an exception represents network offline, DNS, or socket connection failure."""
    if exc is None:
        return False

    current: BaseException | None = exc
    visited = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))

        if isinstance(current, (socket.gaierror, ConnectionError)):
            return True

        if isinstance(current, OSError) and getattr(current, "errno", None) in (
            11001,  # WSAHOST_NOT_FOUND
            10051,  # WSAENETUNREACH
            10054,  # WSAECONNRESET
            10060,  # WSAETIMEDOUT
            10061,  # WSAECONNREFUSED
        ):
            return True

        err_str = str(current).lower()
        if any(marker in err_str for marker in _NETWORK_ERROR_MARKERS):
            return True

        # Check __cause__ or __context__
        current = current.__cause__ or current.__context__

    return False
