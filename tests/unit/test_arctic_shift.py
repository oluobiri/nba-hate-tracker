"""Tests for pipeline.arctic_shift module."""

import time
import pytest
from unittest.mock import patch

import requests

from pipeline.arctic_shift import ArcticShiftClient
from utils.constants import (
    ARCTIC_SHIFT_BASE_URL,
    ARCTIC_SHIFT_COMMENTS_ENDPOINT,
    ARCTIC_SHIFT_POSTS_ENDPOINT,
)


class TestArcticShiftClientInit:
    """Tests for ArcticShiftClient initialization."""

    def test_default_configuration(self):
        """Verify client initializes with default values from constants."""
        client = ArcticShiftClient()

        assert client.base_url == ARCTIC_SHIFT_BASE_URL
        assert client.delay > 0
        assert client.page_size > 0
        assert client.session is not None

    def test_custom_configuration(self):
        """Verify client accepts custom configuration."""
        client = ArcticShiftClient(
            base_url="https://custom.api.com",
            delay=1.0,
            page_size=50,
            rate_limit_buffer=5,
        )

        assert client.base_url == "https://custom.api.com"
        assert client.delay == 1.0
        assert client.page_size == 50
        assert client.rate_limit_buffer == 5


class TestFetchComments:
    """Tests for fetch_comments method."""

    def test_single_page_returns_all_items(
        self, mock_comments_page, mock_empty_response
    ):
        """Verify single-page response yields all items."""
        client = ArcticShiftClient()
        page = mock_comments_page(start_id=1, count=2)

        with patch.object(
            client.session, "get", side_effect=[page, mock_empty_response]
        ):
            results = list(client.fetch_comments("nba", after=0, before=200))

        assert len(results) == 2
        assert results[0]["id"] == "1"
        assert results[1]["id"] == "2"

    def test_pagination_fetches_multiple_pages(
        self, mock_comments_page, mock_empty_response
    ):
        """Verify pagination continues until empty response."""
        client = ArcticShiftClient()
        page1 = mock_comments_page(start_id=1, count=2)
        page2 = mock_comments_page(start_id=3, count=2)

        with patch.object(
            client.session, "get", side_effect=[page1, page2, mock_empty_response]
        ):
            results = list(client.fetch_comments("nba", after=0, before=200))

        assert len(results) == 4
        assert [r["id"] for r in results] == ["1", "2", "3", "4"]

    def test_empty_response_returns_no_items(self, mock_empty_response):
        """Verify empty API response yields nothing."""
        client = ArcticShiftClient()

        with patch.object(client.session, "get", return_value=mock_empty_response):
            results = list(client.fetch_comments("nba", after=0, before=200))

        assert results == []

    def test_uses_correct_endpoint(self, mock_empty_response):
        """Verify fetch_comments uses the comments endpoint."""
        client = ArcticShiftClient()

        with patch.object(
            client.session, "get", return_value=mock_empty_response
        ) as mock_get:
            list(client.fetch_comments("nba", after=0, before=200))

        call_url = mock_get.call_args[0][0]
        assert ARCTIC_SHIFT_COMMENTS_ENDPOINT in call_url

    def test_passes_correct_params(self, mock_empty_response):
        """Verify API params are passed correctly."""
        client = ArcticShiftClient(page_size=50)

        with patch.object(
            client.session, "get", return_value=mock_empty_response
        ) as mock_get:
            list(client.fetch_comments("lakers", after=1000, before=2000))

        call_params = mock_get.call_args[1]["params"]
        assert call_params["subreddit"] == "lakers"
        assert call_params["after"] == 1000
        assert call_params["before"] == 2000
        assert call_params["sort"] == "asc"
        assert call_params["limit"] == 50


class TestFetchPosts:
    """Tests for fetch_posts method."""

    def test_single_page_returns_all_items(self, mock_posts_page, mock_empty_response):
        """Verify single-page response yields all posts."""
        client = ArcticShiftClient()
        page = mock_posts_page(start_id=1, count=2)

        with patch.object(
            client.session, "get", side_effect=[page, mock_empty_response]
        ):
            results = list(client.fetch_posts("nba", after=0, before=200))

        assert len(results) == 2
        assert results[0]["id"] == "post1"

    def test_uses_correct_endpoint(self, mock_empty_response):
        """Verify fetch_posts uses the posts endpoint."""
        client = ArcticShiftClient()

        with patch.object(
            client.session, "get", return_value=mock_empty_response
        ) as mock_get:
            list(client.fetch_posts("nba", after=0, before=200))

        call_url = mock_get.call_args[0][0]
        assert ARCTIC_SHIFT_POSTS_ENDPOINT in call_url


class TestRateLimiting:
    """Tests for rate limit handling."""

    def test_sleeps_when_rate_limit_low(
        self, mock_rate_limited_response, mock_empty_response
    ):
        """Verify client sleeps when approaching rate limit."""
        client = ArcticShiftClient(rate_limit_buffer=10, delay=0)

        # Response with low rate limit (5 < buffer of 10)
        # Reset time is current time + 5 seconds
        reset_time = int(time.time()) + 5
        rate_limited_page = mock_rate_limited_response(
            remaining=5, reset_timestamp=reset_time, count=1
        )

        with patch.object(
            client.session, "get", side_effect=[rate_limited_page, mock_empty_response]
        ):
            with patch("pipeline.arctic_shift.time.sleep") as mock_sleep:
                with patch("pipeline.arctic_shift.time.time", return_value=time.time()):
                    list(client.fetch_comments("nba", after=0, before=200))

        # Should have slept for approximately (reset_time - now + 1) seconds
        mock_sleep.assert_called()
        sleep_duration = mock_sleep.call_args[0][0]
        assert 5 <= sleep_duration <= 7  # reset_time - now + 1, with some tolerance

    def test_sleeps_correct_duration_until_reset(
        self, mock_rate_limited_response, mock_empty_response
    ):
        """Verify sleep duration is calculated from reset timestamp."""
        client = ArcticShiftClient(rate_limit_buffer=10, delay=0)

        # Freeze time for predictable test
        frozen_time = 1000
        reset_time = 1015  # 15 seconds in the future

        rate_limited_page = mock_rate_limited_response(
            remaining=5, reset_timestamp=reset_time, count=1
        )

        with patch.object(
            client.session, "get", side_effect=[rate_limited_page, mock_empty_response]
        ):
            with patch("pipeline.arctic_shift.time.sleep") as mock_sleep:
                with patch("pipeline.arctic_shift.time.time", return_value=frozen_time):
                    list(client.fetch_comments("nba", after=0, before=200))

        # Should sleep for (reset_time - now + 1) = 15 - 0 + 1 = 16 seconds
        mock_sleep.assert_called_with(16)

    def test_sleeps_60s_when_no_reset_header(
        self, mock_api_response, mock_empty_response
    ):
        """Verify client sleeps 60s when rate limit low but no reset time."""
        client = ArcticShiftClient(rate_limit_buffer=10, delay=0)

        # Low rate limit but no reset timestamp
        response = mock_api_response(
            data=[{"id": "1", "created_utc": 100}],
            headers={"X-RateLimit-Remaining": "5"},  # No X-RateLimit-Reset
        )

        with patch.object(
            client.session, "get", side_effect=[response, mock_empty_response]
        ):
            with patch("pipeline.arctic_shift.time.sleep") as mock_sleep:
                list(client.fetch_comments("nba", after=0, before=200))

        mock_sleep.assert_called_with(60)

    def test_no_sleep_when_rate_limit_ok(self, mock_api_response, mock_empty_response):
        """Verify client doesn't sleep when rate limit is healthy."""
        client = ArcticShiftClient(rate_limit_buffer=10, delay=0)

        # Response with healthy rate limit (100 > buffer of 10)
        response = mock_api_response(
            data=[{"id": "1", "created_utc": 100}],
            headers={"X-RateLimit-Remaining": "100"},
        )

        with patch.object(
            client.session, "get", side_effect=[response, mock_empty_response]
        ):
            with patch("pipeline.arctic_shift.time.sleep") as mock_sleep:
                list(client.fetch_comments("nba", after=0, before=200))

        # Should not have slept at all (delay=0, rate limit healthy)
        mock_sleep.assert_not_called()

    def test_no_sleep_when_no_rate_limit_headers(
        self, mock_comments_page, mock_empty_response
    ):
        """Verify client doesn't sleep when API returns no rate limit headers."""
        client = ArcticShiftClient(rate_limit_buffer=10, delay=0)
        page = mock_comments_page(start_id=1, count=1)  # No rate limit headers

        with patch.object(
            client.session, "get", side_effect=[page, mock_empty_response]
        ):
            with patch("pipeline.arctic_shift.time.sleep") as mock_sleep:
                list(client.fetch_comments("nba", after=0, before=200))

        mock_sleep.assert_not_called()


class TestErrorHandling:
    """Tests for error handling."""

    def test_http_error_raises_exception(self, mock_api_response):
        """Verify HTTP errors are raised as exceptions."""
        client = ArcticShiftClient()
        mock_response = mock_api_response(data=[])
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        with patch.object(client.session, "get", return_value=mock_response):
            with pytest.raises(requests.HTTPError):
                list(client.fetch_comments("nba", after=0, before=200))

    def test_connection_error_raises_exception(self):
        """Verify connection errors propagate."""
        client = ArcticShiftClient()

        with patch.object(
            client.session,
            "get",
            side_effect=requests.ConnectionError("Connection failed"),
        ):
            with pytest.raises(requests.ConnectionError):
                list(client.fetch_comments("nba", after=0, before=200))


class TestSessionManagement:
    """Tests for session management."""

    def test_session_reused_across_requests(
        self, mock_comments_page, mock_empty_response
    ):
        """Verify same session is used for multiple requests."""
        client = ArcticShiftClient()
        page = mock_comments_page(start_id=1, count=1)

        with patch.object(
            client.session, "get", side_effect=[page, mock_empty_response]
        ) as mock_get:
            list(client.fetch_comments("nba", after=0, before=200))

        # Both calls should have gone through the same session.get
        assert mock_get.call_count == 2

    def test_close_closes_session(self):
        """Verify close() closes the underlying session."""
        client = ArcticShiftClient()

        with patch.object(client.session, "close") as mock_close:
            client.close()

        mock_close.assert_called_once()

    def test_context_manager_support(self):
        """Verify client can be used as context manager."""
        with ArcticShiftClient() as client:
            assert client.session is not None
