"""Pytest configuration ensuring JOT_TESTING environment variable is set."""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ["JOT_TESTING"] = "1"
# Lessons and summaries never land in the real Documents folder during tests,
# and no browser is started to print PDFs.
os.environ.setdefault("JOT_COURSE_ROOT", tempfile.mkdtemp(prefix="jot_test_courses_"))
os.environ.setdefault("JOT_NO_PDF", "1")


@pytest.fixture(autouse=True)
def isolate_credential_runtime():
    from jot.services import config_service, generation_service

    config_service._credential_overrides.clear()
    generation_service.reset_model_overload()
    yield
    config_service._credential_overrides.clear()
    generation_service.reset_model_overload()
