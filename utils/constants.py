"""
Project-wide constants for NBA Hate Tracker.

Centralized here so they can be imported by scripts, tests,
and eventually the frontend.
"""

# All NBA-related subreddits we're tracking.
# Lowercase for consistent comparison — always normalize input before checking.
TARGET_SUBREDDITS: set[str] = {
    # Main NBA subreddit
    "nba",
    # Eastern Conference - Atlantic
    "bostonceltics",
    "gonets",
    "nyknicks", 
    "sixers",
    "torontoraptors",
    # Eastern Conference - Central
    "chicagobulls",
    "clevelandcavs",
    "detroitpistons",
    "pacers",
    "mkebucks",
    # Eastern Conference - Southeast
    "atlantahawks",
    "charlottehornets",
    "heat",
    "orlandomagic",
    "washingtonwizards",
    # Western Conference - Northwest
    "denvernuggets",
    "timberwolves",
    "thunder",
    "ripcity",
    "utahjazz",
    # Western Conference - Pacific
    "warriors",
    "laclippers",
    "lakers",
    "suns",
    "kings",
    # Western Conference - Southwest
    "mavericks",
    "rockets",
    "memphisgrizzlies",
    "nolapelicans",
    "nbaspurs",
}

# Fields we extract from raw Reddit comments.
# Everything else is discarded to save space.
REQUIRED_FIELDS: set[str] = {
    "id",
    "body", 
    "subreddit",
    "created_utc",
}

OPTIONAL_FIELDS: set[str] = {
    "author",
    "author_flair_text",
    "author_flair_css_class",
    "score",
    "controversiality",
    "parent_id",
    "link_id",
}

# Body values that indicate deleted/removed content — treat as invalid
INVALID_BODY_VALUES: set[str] = {
    "[deleted]",
    "[removed]",
    "",
}