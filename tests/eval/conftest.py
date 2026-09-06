"""Fixtures for the live classifier eval suites."""

import os

import pytest
from dotenv import load_dotenv

from pipeline.evaluation import classify_cases, load_cases
from pipeline.targets import classify_target_cases, load_target_cases


def _require_api_key() -> None:
    """Skip (rather than fail) when ANTHROPIC_API_KEY is unavailable."""
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set; eval suite requires live API access")


@pytest.fixture(scope="session")
def eval_results() -> dict[str, dict]:
    """Classify all sentiment cases once per session (one live call each)."""
    _require_api_key()
    return classify_cases(load_cases())


@pytest.fixture(scope="session")
def target_results() -> dict[str, dict]:
    """Verify all target cases once per session (one live call each)."""
    _require_api_key()
    return classify_target_cases(load_target_cases())
