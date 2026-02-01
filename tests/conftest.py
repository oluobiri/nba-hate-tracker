"""
Pytest fixtures for NBA Hate Tracker tests.

Fixtures provide reusable test data and utilities. They're injected
into test functions by name — pytest handles the wiring automatically.
"""

import json
from typing import Callable
from unittest.mock import Mock

import pytest
from pathlib import Path

# ---------------------------------------------------------------------------
# Sample comment data
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_nba_comment() -> dict:
    """
    A well-formed comment from a target subreddit.

    This represents the 'happy path' — exactly what we expect
    to extract and keep.
    """
    return {
        "id": "abc123",
        "body": "LeBron is washed, can't believe we traded for him",
        "author": "hoopsfan42",
        "author_flair_text": "Lakers",
        "author_flair_css_class": "lakers",
        "subreddit": "nba",
        "created_utc": 1709251200,
        "score": 42,
        "controversiality": 0,
        "parent_id": "t1_xyz789",
        "link_id": "t3_post123",
    }


@pytest.fixture
def valid_team_subreddit_comment() -> dict:
    """Comment from a team-specific subreddit (not r/nba)."""
    return {
        "id": "def456",
        "body": "Tatum is carrying this team",
        "author": "celticspride",
        "author_flair_text": "Banner 18",
        "author_flair_css_class": "celtics",
        "subreddit": "bostonceltics",
        "created_utc": 1709337600,
        "score": 156,
        "controversiality": 0,
        "parent_id": "t1_aaa111",
        "link_id": "t3_post456",
    }


@pytest.fixture
def wrong_subreddit_comment() -> dict:
    """
    Comment from a subreddit we don't care about.

    This should be filtered OUT by our extraction logic.
    """
    return {
        "id": "xyz789",
        "body": "Great goal by Messi!",
        "author": "soccerfan",
        "author_flair_text": "Barcelona",
        "author_flair_css_class": "barca",
        "subreddit": "soccer",
        "created_utc": 1709251200,
        "score": 1024,
        "controversiality": 0,
        "parent_id": "t1_bbb222",
        "link_id": "t3_post789",
    }


@pytest.fixture
def uppercase_subreddit_comment() -> dict:
    """
    Comment with inconsistent subreddit casing.

    Reddit data is messy — subreddit names appear as 'nba', 'NBA', 'Nba'.
    Our filter must handle all variants.
    """
    return {
        "id": "case123",
        "body": "This is a test comment",
        "author": "testuser",
        "author_flair_text": None,
        "author_flair_css_class": None,
        "subreddit": "NBA",  # Uppercase!
        "created_utc": 1709251200,
        "score": 1,
        "controversiality": 0,
        "parent_id": "t1_ccc333",
        "link_id": "t3_post000",
    }


@pytest.fixture
def missing_body_comment() -> dict:
    """
    Comment where body field is missing entirely.

    Useless for sentiment analysis — should be rejected but logged.
    """
    return {
        "id": "nobody123",
        "author": "deleteduser",
        "author_flair_text": None,
        "author_flair_css_class": None,
        "subreddit": "nba",
        "created_utc": 1709251200,
        "score": 0,
        "controversiality": 0,
        "parent_id": "t1_ddd444",
        "link_id": "t3_post111",
        # Note: no "body" key at all
    }


@pytest.fixture
def deleted_body_comment() -> dict:
    """
    Comment where body is [deleted] or [removed].

    Reddit replaces content with these placeholders. Also useless.
    """
    return {
        "id": "deleted123",
        "body": "[deleted]",
        "author": "[deleted]",
        "author_flair_text": None,
        "author_flair_css_class": None,
        "subreddit": "lakers",
        "created_utc": 1709251200,
        "score": 5,
        "controversiality": 0,
        "parent_id": "t1_eee555",
        "link_id": "t3_post222",
    }


@pytest.fixture
def empty_body_comment() -> dict:
    """Comment with empty string body."""
    return {
        "id": "empty123",
        "body": "",
        "author": "quietuser",
        "author_flair_text": "Heat",
        "author_flair_css_class": "heat",
        "subreddit": "heat",
        "created_utc": 1709251200,
        "score": 1,
        "controversiality": 0,
        "parent_id": "t1_fff666",
        "link_id": "t3_post333",
    }


# ---------------------------------------------------------------------------
# Batch fixtures — for testing multiple records at once
# ---------------------------------------------------------------------------


@pytest.fixture
def mixed_comments_batch(
    valid_nba_comment,
    valid_team_subreddit_comment,
    wrong_subreddit_comment,
    missing_body_comment,
) -> list[dict]:
    """
    A batch with a mix of valid and invalid comments.

    Useful for testing filter logic processes batches correctly.
    Expected: 2 accepted (nba + bostonceltics), 2 rejected.
    """
    return [
        valid_nba_comment,
        valid_team_subreddit_comment,
        wrong_subreddit_comment,
        missing_body_comment,
    ]


# ---------------------------------------------------------------------------
# File-based fixtures — for integration-style tests
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_jsonl_file(tmp_path, mixed_comments_batch) -> Path:
    """
    Creates a temporary .jsonl file with test data.

    tmp_path is a built-in pytest fixture that provides a unique
    temporary directory for each test. Automatically cleaned up.
    """
    filepath = tmp_path / "test_comments.jsonl"
    with open(filepath, "w") as f:
        for comment in mixed_comments_batch:
            f.write(json.dumps(comment) + "\n")
    return filepath


@pytest.fixture
def malformed_jsonl_file(tmp_path) -> Path:
    """
    JSONL file with some corrupted lines.

    Tests that our parser handles bad data gracefully
    instead of crashing the whole pipeline.
    """
    filepath = tmp_path / "malformed_comments.jsonl"
    lines = [
        '{"id": "good1", "body": "valid json", "subreddit": "nba"}',
        "this is not json at all",
        '{"id": "good2", "body": "also valid", "subreddit": "nba"}',
        '{"incomplete": "json',
        '{"id": "good3", "body": "still going", "subreddit": "nba"}',
    ]
    filepath.write_text("\n".join(lines))
    return filepath


# ---------------------------------------------------------------------------
# API mock fixtures — for Arctic Shift client tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_api_response() -> Callable[[list[dict], dict[str, str] | None], Mock]:
    """
    Factory fixture for creating mock API responses.

    Returns a function that creates a Mock with the specified data and headers.

    Usage:
        response = mock_api_response([{"id": "1"}], {"X-RateLimit-Remaining": "100"})
    """

    def _create_response(
        data: list[dict],
        headers: dict[str, str] | None = None,
    ) -> Mock:
        mock = Mock()
        mock.json.return_value = {"data": data}
        mock.headers = headers or {}
        mock.raise_for_status = Mock()
        return mock

    return _create_response


@pytest.fixture
def mock_empty_response(mock_api_response) -> Mock:
    """Empty API response — signals end of pagination."""
    return mock_api_response(data=[], headers={})


@pytest.fixture
def mock_comments_page(mock_api_response) -> Callable[[int, int], Mock]:
    """
    Factory for creating mock comment page responses.

    Creates comments with sequential IDs and timestamps.

    Usage:
        page = mock_comments_page(start_id=1, count=2)
        # Creates comments with id="1", id="2"
    """

    def _create_page(start_id: int = 1, count: int = 2) -> Mock:
        comments = [
            {"id": str(i), "body": f"comment {i}", "created_utc": 100 + i}
            for i in range(start_id, start_id + count)
        ]
        return mock_api_response(data=comments, headers={})

    return _create_page


@pytest.fixture
def mock_posts_page(mock_api_response) -> Callable[[int, int], Mock]:
    """
    Factory for creating mock post page responses.

    Creates posts with sequential IDs and timestamps.
    """

    def _create_page(start_id: int = 1, count: int = 2) -> Mock:
        posts = [
            {"id": f"post{i}", "title": f"Post {i}", "created_utc": 100 + i}
            for i in range(start_id, start_id + count)
        ]
        return mock_api_response(data=posts, headers={})

    return _create_page


@pytest.fixture
def mock_rate_limited_response(mock_api_response) -> Callable[[int, int, int], Mock]:
    """
    Factory for creating responses with rate limit headers.

    Args:
        remaining: X-RateLimit-Remaining value
        reset_timestamp: X-RateLimit-Reset Unix timestamp
        count: Number of items in response
    """

    def _create_response(
        remaining: int,
        reset_timestamp: int,
        count: int = 1,
    ) -> Mock:
        data = [
            {"id": str(i), "body": f"comment {i}", "created_utc": 100 + i}
            for i in range(1, count + 1)
        ]
        headers = {
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_timestamp),
        }
        return mock_api_response(data=data, headers=headers)

    return _create_response


# ---------------------------------------------------------------------------
# Player mention fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def player_mention_comment() -> dict:
    """Comment that mentions a tracked player (LeBron)."""
    return {
        "id": "player123",
        "body": "LeBron is washed, can't believe we traded for him",
        "author": "hoopsfan42",
        "author_flair_text": "Lakers",
        "author_flair_css_class": "lakers",
        "subreddit": "nba",
        "created_utc": 1709251200,
        "score": 42,
        "controversiality": 0,
        "parent_id": "t1_xyz789",
        "link_id": "t3_post123",
    }


@pytest.fixture
def no_player_mention_comment() -> dict:
    """Comment with no tracked player mentions."""
    return {
        "id": "noplayer456",
        "body": "Great game last night, really exciting finish",
        "author": "casualfan",
        "author_flair_text": None,
        "author_flair_css_class": None,
        "subreddit": "nba",
        "created_utc": 1709251200,
        "score": 10,
        "controversiality": 0,
        "parent_id": "t1_aaa111",
        "link_id": "t3_post456",
    }


@pytest.fixture
def short_alias_false_positive_comment() -> dict:
    """
    Comment with words containing short aliases as substrings.

    Tests word boundary matching - 'AD' should not match 'advertisement'.
    """
    return {
        "id": "falsepos789",
        "body": "This advertisement for java programming is bad",
        "author": "techfan",
        "author_flair_text": None,
        "author_flair_css_class": None,
        "subreddit": "nba",
        "created_utc": 1709251200,
        "score": 5,
        "controversiality": 0,
        "parent_id": "t1_bbb222",
        "link_id": "t3_post789",
    }


# ---------------------------------------------------------------------------
# Batch API / Sentiment response fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_sentiment_responses() -> list[tuple[str, dict]]:
    """
    Valid JSON responses from sentiment classification.

    Returns list of (raw_response, expected_parsed) tuples.
    """
    return [
        (
            '{"s": "pos", "c": 0.95, "p": "LeBron James"}',
            {"s": "pos", "c": 0.95, "p": "LeBron James"},
        ),
        (
            '{"s": "neg", "c": 0.8, "p": "Russell Westbrook"}',
            {"s": "neg", "c": 0.8, "p": "Russell Westbrook"},
        ),
        (
            '{"s": "neu", "c": 0.6, "p": null}',
            {"s": "neu", "c": 0.6, "p": None},
        ),
        (
            '{"s": "pos", "c": 0.9, "p": null}',
            {"s": "pos", "c": 0.9, "p": None},
        ),
    ]


@pytest.fixture
def markdown_wrapped_responses() -> list[tuple[str, str, str | None]]:
    """
    Responses wrapped in markdown code blocks.

    Returns list of (raw_response, expected_sentiment, expected_player) tuples.
    """
    return [
        ('```json\n{"s": "pos", "c": 0.9, "p": "LeBron James"}\n```', "pos", "LeBron James"),
        ('```\n{"s": "neg", "c": 0.75, "p": null}\n```', "neg", None),
        ('```json{"s": "neu", "c": 0.5, "p": "Curry"}```', "neu", "Curry"),
    ]


@pytest.fixture
def malformed_responses() -> list[str]:
    """
    Malformed responses that should return error dicts.

    Includes: non-JSON, wrong field names, invalid values, etc.
    """
    return [
        "not json at all",
        '{"sentiment": "positive"}',  # Wrong field names
        '{"s": "invalid", "c": 0.5}',  # Invalid sentiment value
        "{malformed json",
        "[]",  # Array instead of object
    ]
