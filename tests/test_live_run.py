"""Ticket 28: the manual live run. Excluded from `pytest` and CI by the `live` marker; run it with
`uv run pytest -m live`. Needs GEMINI_API_KEY (environment or the git-ignored .env); reads through the
cache in storage/live-cache, so a second run makes zero API calls."""

import os

import pytest

from hermes import live

pytestmark = pytest.mark.live


def test_live_scenarios_evaluation_and_injection_samples():
    live.load_env()
    if not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("no GEMINI_API_KEY")
    assert live.main(["scenarios", "eval", "injection", "--report", "storage/live-report.md"]) == 0
