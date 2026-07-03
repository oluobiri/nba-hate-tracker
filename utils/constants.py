"""
Constants for the NBA Hate Tracker project.

This module contains:
- Data validation constants
- Arctic Shift API configuration
- Season date boundaries
"""

# =============================================================================
# DATA VALIDATION
# =============================================================================

# Fields we extract from each comment (11 total, down from ~60 in raw data)
REQUIRED_FIELDS = [
    "id",
    "body",
    "author",
    "author_flair_text",
    "author_flair_css_class",
    "subreddit",
    "created_utc",
    "score",
    "controversiality",
    "parent_id",
    "link_id",
]

# Body values that indicate deleted/removed content (skip these)
INVALID_BODY_VALUES = frozenset(
    [
        "[deleted]",
        "[removed]",
        "",
    ]
)


# =============================================================================
# ARCTIC SHIFT API CONFIGURATION
# =============================================================================

# Base URL for Arctic Shift API (public endpoint, not a secret)
ARCTIC_SHIFT_BASE_URL = "https://arctic-shift.photon-reddit.com"

# Comments search endpoint
ARCTIC_SHIFT_COMMENTS_ENDPOINT = "/api/comments/search"

# Posts search endpoint
ARCTIC_SHIFT_POSTS_ENDPOINT = "/api/posts/search"

# Maximum items per API request (API limit is higher, but we stay conservative)
ARCTIC_SHIFT_PAGE_SIZE = 100

# Delay between requests in seconds (be respectful to free service)
ARCTIC_SHIFT_REQUEST_DELAY = 0.5

# Rate limit buffer - sleep when remaining requests drop below this
ARCTIC_SHIFT_RATE_LIMIT_BUFFER = 10

# Total attempts per page request (1 initial + retries)
ARCTIC_SHIFT_MAX_ATTEMPTS = 4

# Base seconds for exponential backoff between retries (2s -> 4s -> 8s)
ARCTIC_SHIFT_RETRY_BACKOFF = 2.0

# HTTP statuses treated as transient. 422 is included deliberately: the API
# intermittently surfaces backend hiccups as 422 on requests that succeed
# when replayed (observed 2026-07-02 on the v2 season download).
ARCTIC_SHIFT_RETRYABLE_STATUSES = frozenset({422, 500, 502, 503, 504})



# =============================================================================
# FILE PATHS (relative subdirectories - root comes from environment)
# =============================================================================

RAW_DATA_SUBDIR = "raw"
FILTERED_DATA_SUBDIR = "filtered"
PROGRESS_FILENAME = ".progress.json"
BATCHES_DATA_SUBDIR = "batches"
PROCESSED_DATA_SUBDIR = "processed"
DASHBOARD_DATA_SUBDIR = "dashboard"