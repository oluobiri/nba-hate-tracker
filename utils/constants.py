"""
Constants for the NBA Hate Tracker project.

This module contains:
- Target subreddits for data collection
- Data validation constants
- Arctic Shift API configuration
- Season date boundaries
"""

# =============================================================================
# TARGET SUBREDDITS
# =============================================================================

# Primary subreddit
PRIMARY_SUBREDDIT = "nba"

# Team subreddits (30 total)
TEAM_SUBREDDITS = [
    # Atlantic Division
    "bostonceltics",
    "gonets",
    "nyknicks",
    "sixers",
    "torontoraptors",
    # Central Division
    "chicagobulls",
    "clevelandcavs",
    "detroitpistons",
    "pacers",
    "mkebucks",
    # Southeast Division
    "atlantahawks",
    "charlottehornets",
    "heat",
    "orlandomagic",
    "washingtonwizards",
    # Northwest Division
    "denvernuggets",
    "timberwolves",
    "thunder",
    "ripcity",
    "utahjazz",
    # Pacific Division
    "warriors",
    "laclippers",
    "lakers",
    "suns",
    "kings",
    # Southwest Division
    "mavericks",
    "rockets",
    "memphisgrizzlies",
    "nolapelicans",
    "nbaspurs",
]

# Combined list for iteration (nba first, then teams alphabetically isn't 
# necessary but we put the big one first so we see progress early)
TARGET_SUBREDDITS = [PRIMARY_SUBREDDIT] + TEAM_SUBREDDITS


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
INVALID_BODY_VALUES = frozenset([
    "[deleted]",
    "[removed]",
    "",
])


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


# =============================================================================
# SEASON BOUNDARIES
# =============================================================================

# 2024-25 NBA Season data collection window
# Regular season: Oct 22, 2024 - Apr 13, 2025
# Playoffs: Apr 19, 2025 - ~June 2025
# We start Oct 1 to capture preseason discussion

SEASON_START_DATE = "2024-10-01"
SEASON_END_DATE = "2025-06-30"


# =============================================================================
# FILE PATHS (relative subdirectories - root comes from environment)
# =============================================================================

RAW_DATA_SUBDIR = "raw"
FILTERED_DATA_SUBDIR = "filtered"
PROGRESS_FILENAME = ".progress.json"