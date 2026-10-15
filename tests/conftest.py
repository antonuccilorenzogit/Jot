"""Pytest configuration ensuring JOT_TESTING environment variable is set."""

from __future__ import annotations

import os

import pytest

os.environ["JOT_TESTING"] = "1"


@pytest.fixture(autouse=True)
def isolate_credential_runtime():
    from jot.services import config_service

    config_service._credential_overrides.clear()
    yield
    config_service._credential_overrides.clear()
