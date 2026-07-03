"""
Arctic Shift API client for fetching Reddit data.

This module provides a reusable client for the Arctic Shift API, which serves
archived Reddit data. The client handles pagination, rate limiting, and
connection management.

Usage:
    from pipeline.arctic_shift import ArcticShiftClient

    with ArcticShiftClient() as client:
        for comment in client.fetch_comments("nba", after=start_ts, before=end_ts):
            process(comment)
"""

import logging
import time
from collections.abc import Iterator
from typing import Any

import requests

from utils.constants import (
    ARCTIC_SHIFT_BASE_URL,
    ARCTIC_SHIFT_COMMENTS_ENDPOINT,
    ARCTIC_SHIFT_MAX_ATTEMPTS,
    ARCTIC_SHIFT_PAGE_SIZE,
    ARCTIC_SHIFT_POSTS_ENDPOINT,
    ARCTIC_SHIFT_RATE_LIMIT_BUFFER,
    ARCTIC_SHIFT_REQUEST_DELAY,
    ARCTIC_SHIFT_RETRY_BACKOFF,
    ARCTIC_SHIFT_RETRYABLE_STATUSES,
)

logger = logging.getLogger(__name__)


def _is_retryable(error: requests.RequestException) -> bool:
    """
    Check whether a request error is worth retrying.

    Connection errors and timeouts are always transient. HTTP errors are
    retryable only for statuses in ARCTIC_SHIFT_RETRYABLE_STATUSES; other
    client errors (e.g. 404) indicate a real problem with the request.

    Args:
        error: The exception raised by the request.

    Returns:
        True if the request should be retried.
    """
    if isinstance(error, requests.HTTPError):
        if error.response is None:
            return False
        return error.response.status_code in ARCTIC_SHIFT_RETRYABLE_STATUSES
    return isinstance(error, (requests.ConnectionError, requests.Timeout))


class ArcticShiftClient:
    """
    Client for Arctic Shift Reddit archive API.

    Handles pagination, rate limiting, and connection pooling automatically.
    Can be used as a context manager for automatic resource cleanup.

    Args:
        base_url: API base URL. Defaults to Arctic Shift public endpoint.
        delay: Seconds to wait between requests. Defaults to 0.5s.
        page_size: Max items per request. Defaults to 100.
        rate_limit_buffer: Sleep when remaining requests fall below this. Defaults to 10.
        max_attempts: Total attempts per page request (1 initial + retries). Defaults to 4.
        retry_backoff: Base seconds for exponential backoff between retries. Defaults to 2.0.

    Example:
        with ArcticShiftClient() as client:
            for comment in client.fetch_comments("nba", after=1000, before=2000):
                print(comment["body"])
    """

    def __init__(
        self,
        base_url: str = ARCTIC_SHIFT_BASE_URL,
        delay: float = ARCTIC_SHIFT_REQUEST_DELAY,
        page_size: int = ARCTIC_SHIFT_PAGE_SIZE,
        rate_limit_buffer: int = ARCTIC_SHIFT_RATE_LIMIT_BUFFER,
        max_attempts: int = ARCTIC_SHIFT_MAX_ATTEMPTS,
        retry_backoff: float = ARCTIC_SHIFT_RETRY_BACKOFF,
    ) -> None:
        """Initialize the client with configuration."""
        self.base_url = base_url
        self.delay = delay
        self.page_size = page_size
        self.rate_limit_buffer = rate_limit_buffer
        self.max_attempts = max_attempts
        self.retry_backoff = retry_backoff
        self.session = requests.Session()

    def __enter__(self) -> "ArcticShiftClient":
        """Enter context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit context manager and close session."""
        self.close()

    def fetch_comments(
        self,
        subreddit: str,
        after: int,
        before: int,
    ) -> Iterator[dict]:
        """
        Fetch all comments for a subreddit in a time range.

        Handles pagination automatically, yielding comments one at a time.
        This is memory-efficient for large datasets.

        Args:
            subreddit: Subreddit name (without r/ prefix).
            after: Unix timestamp - fetch comments AFTER this time.
            before: Unix timestamp - fetch comments BEFORE this time.

        Yields:
            Comment dicts from the API.

        Raises:
            requests.HTTPError: If API returns an error status.
            requests.ConnectionError: If connection fails.
        """
        yield from self._fetch_paginated(
            endpoint=ARCTIC_SHIFT_COMMENTS_ENDPOINT,
            subreddit=subreddit,
            after=after,
            before=before,
        )

    def fetch_posts(
        self,
        subreddit: str,
        after: int,
        before: int,
    ) -> Iterator[dict]:
        """
        Fetch all posts for a subreddit in a time range.

        Handles pagination automatically, yielding posts one at a time.
        This is memory-efficient for large datasets.

        Args:
            subreddit: Subreddit name (without r/ prefix).
            after: Unix timestamp - fetch posts AFTER this time.
            before: Unix timestamp - fetch posts BEFORE this time.

        Yields:
            Post dicts from the API.

        Raises:
            requests.HTTPError: If API returns an error status.
            requests.ConnectionError: If connection fails.
        """
        yield from self._fetch_paginated(
            endpoint=ARCTIC_SHIFT_POSTS_ENDPOINT,
            subreddit=subreddit,
            after=after,
            before=before,
        )

    def _fetch_paginated(
        self,
        endpoint: str,
        subreddit: str,
        after: int,
        before: int,
    ) -> Iterator[dict]:
        """
        Fetch all items from an endpoint with automatic pagination.

        Uses created_utc ascending sort for stable pagination.
        Continues fetching until an empty response is received.

        Args:
            endpoint: API endpoint path (e.g., "/api/comments/search").
            subreddit: Subreddit name.
            after: Start timestamp (exclusive).
            before: End timestamp (exclusive).

        Yields:
            Item dicts from the API.
        """
        current_after = after

        while current_after < before:
            items, headers = self._fetch_page(
                endpoint=endpoint,
                subreddit=subreddit,
                after=current_after,
                before=before,
            )

            if not items:
                # No more items in range
                break

            yield from items

            # Update cursor to last item's timestamp + 1 to avoid refetching
            last_timestamp = items[-1].get("created_utc", current_after)
            current_after = last_timestamp + 1

            # Respect rate limits
            self._check_rate_limit(headers)

            # Be nice to the API
            if self.delay > 0:
                time.sleep(self.delay)

    def _fetch_page(
        self,
        endpoint: str,
        subreddit: str,
        after: int,
        before: int,
    ) -> tuple[list[dict], dict[str, str]]:
        """
        Fetch a single page from the API, retrying transient failures.

        Connection errors, timeouts, and transient HTTP statuses (5xx, 429,
        and 422 — which this API intermittently returns for requests that
        succeed on replay) are retried with exponential backoff up to
        max_attempts. Other HTTP errors raise immediately.

        Args:
            endpoint: API endpoint path.
            subreddit: Subreddit name.
            after: Start timestamp.
            before: End timestamp.

        Returns:
            Tuple of (list of item dicts, response headers).

        Raises:
            requests.HTTPError: If API returns a non-transient error status,
                or a transient one on every attempt.
            requests.ConnectionError: If connection fails on every attempt.
        """
        url = f"{self.base_url}{endpoint}"

        params = {
            "subreddit": subreddit,
            "after": after,
            "before": before,
            "sort": "asc",
            "limit": self.page_size,
        }

        last_error: requests.RequestException | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.get(url, params=params, timeout=60)
                response.raise_for_status()
                data = response.json()
                return data.get("data", []), dict(response.headers)
            except requests.RequestException as e:
                if not _is_retryable(e):
                    raise
                last_error = e
                if attempt < self.max_attempts:
                    wait = self.retry_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        f"Transient API error (attempt {attempt}/{self.max_attempts}), "
                        f"retrying in {wait:.0f}s: {e}"
                    )
                    time.sleep(wait)

        raise last_error  # type: ignore[misc]  # loop always sets it before exiting

    def _check_rate_limit(self, headers: dict[str, str]) -> None:
        """
        Check rate limit headers and sleep if necessary.

        Arctic Shift returns:
            X-RateLimit-Remaining: requests left in window
            X-RateLimit-Reset: Unix timestamp when limit resets

        Sleeps proactively if remaining drops below buffer threshold.

        Args:
            headers: Response headers dict.
        """
        remaining_str = headers.get("X-RateLimit-Remaining")

        if remaining_str is None:
            # No rate limit headers - API might not always include them
            return

        remaining = int(remaining_str)

        if remaining < self.rate_limit_buffer:
            reset_time_str = headers.get("X-RateLimit-Reset")
            if reset_time_str:
                reset_ts = int(reset_time_str)
                sleep_seconds = max(0, reset_ts - int(time.time())) + 1
            else:
                # No reset time provided, use conservative sleep
                sleep_seconds = 60

            logger.warning(
                f"Rate limit low ({remaining} remaining). "
                f"Sleeping {sleep_seconds}s until reset."
            )
            time.sleep(sleep_seconds)

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()
