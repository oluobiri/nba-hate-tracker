"""
Constants for the NBA Hate Tracker project.

This module contains:
- Data validation constants
- Arctic Shift API configuration
- NBA Stats API configuration
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

# Total attempts per page request (1 initial + retries). Sized for
# correlated failure bursts (origin restarts), not just single-request
# blips: 6 attempts -> 2+4+8+16+32 = 62s of coverage, which rides out
# short restarts (observed 2026-07-04: a burst outlasted the previous
# ~14s window). Bursts longer than the window still exhaust retries;
# the download script's resume-from-file is the backstop there.
ARCTIC_SHIFT_MAX_ATTEMPTS = 6

# Base seconds for exponential backoff between retries (2s -> 4s -> ... -> 32s)
ARCTIC_SHIFT_RETRY_BACKOFF = 2.0

# HTTP statuses treated as transient. 422 is included deliberately: the API
# intermittently surfaces backend hiccups as 422 on requests that succeed
# when replayed (observed 2026-07-02 on the v2 season download). 429 is
# normally avoided via the rate-limit headers, but retrying covers the case
# where those headers are absent. The Cloudflare 52x family is origin-side
# (520 "unknown response" killed the first v2 download attempt; 521-524 are
# origin down/unreachable/timeout) — transient by nature, never client error.
ARCTIC_SHIFT_RETRYABLE_STATUSES = frozenset(
    {422, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
)


# =============================================================================
# NBA STATS API CONFIGURATION (stats.nba.com via nba_api)
# =============================================================================

# Delay between per-team roster requests in seconds (be polite to
# stats.nba.com — it rate-limits aggressively and bans are opaque)
NBA_STATS_REQUEST_DELAY = 0.6

# Per-request timeout in seconds. stats.nba.com's characteristic failure
# mode is hanging, not erroring — a bounded timeout is what converts a
# hang into a retryable Timeout.
NBA_STATS_TIMEOUT = 30

# Total attempts per endpoint call (1 initial + retries). The full fetch
# is only 30 requests, so unlike the Arctic Shift download there is no
# long burst to ride out: 4 attempts -> 2+4+8 = 14s of coverage per call.
NBA_STATS_MAX_ATTEMPTS = 4

# Base seconds for exponential backoff between retries (2s -> 4s -> 8s)
NBA_STATS_RETRY_BACKOFF = 2.0


# =============================================================================
# AGGREGATION - comment_samples selection (pipeline/aggregation.py)
# =============================================================================
# The keyword defaults of build_comment_samples(), named so the manifest can
# import rather than retype the rule. Finalized on 2025-26 data: every
# qualified player's cells fill at n=10; the cap removes ~2% of the candidate
# pool; the floor keeps the classifier's top two confidence buckets on the
# polar labels (pos/neg only - neu sits at a conventional 0.5 and is exempt).

COMMENT_SAMPLES_TOP_N = 10
COMMENT_SAMPLES_MIN_CONFIDENCE = 0.9
COMMENT_SAMPLES_MAX_BODY_CHARS = 500

# =============================================================================
# FILE PATHS (relative subdirectories - root comes from environment)
# =============================================================================

RAW_DATA_SUBDIR = "raw"
FILTERED_DATA_SUBDIR = "filtered"
PROGRESS_FILENAME = ".progress.json"
BATCHES_DATA_SUBDIR = "batches"
PROCESSED_DATA_SUBDIR = "processed"
DASHBOARD_DATA_SUBDIR = "dashboard"
REFERENCE_DATA_SUBDIR = "reference"
