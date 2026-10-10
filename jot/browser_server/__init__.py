"""
Browser server package for jot.

Provides a local FastAPI host and WebSocket dispatcher for agentic debugging,
browser development, and Playwright E2E testing.
"""

from __future__ import annotations

from jot.browser_server.server import create_browser_app
from jot.browser_server.ws_dispatcher import WebSocketDispatcher

__all__ = ["WebSocketDispatcher", "create_browser_app"]
