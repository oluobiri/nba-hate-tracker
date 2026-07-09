"""Fixtures for the live classifier eval suite."""

import os

import pytest
from dotenv import load_dotenv

from pipeline.evaluation import classify_cases, load_cases


@pytest.fixture(scope="session")
def eval_results() -> dict[str, dict]:
    """
    Classify all cases once per session (~23 live API calls).

    Skips (rather than fails) when ANTHROPIC_API_KEY is unavailable, so
    the eval suite degrades cleanly on machines without credentials.
    """
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set; eval suite requires live API access")
    return classify_cases(load_cases())
