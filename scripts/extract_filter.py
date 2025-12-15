"""Extract and filter Reddit comments from ZST archive dumps."""

from utils.constants import TARGET_SUBREDDITS, INVALID_BODY_VALUES

def is_target_subreddit(comment: dict) -> bool:
    """Check if comment is from a subreddit we're tracking"""
    subreddit = comment.get("subreddit", "")
    return subreddit.lower() in TARGET_SUBREDDITS

def has_valid_body(comment: dict) -> bool:
    """Check if comment has a complete body."""
    body = comment.get("body", "")
    # catch None and empty strings
    if not body:
        return False   
    return body not in INVALID_BODY_VALUES