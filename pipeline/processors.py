"""
Comment processing pipeline with configurable filter steps.

This module provides reusable filter functions and a pipeline class
for processing Reddit comments through multiple validation stages.
"""

import logging
import re
from collections.abc import Callable

from utils.constants import INVALID_BODY_VALUES, REQUIRED_FIELDS
from utils.player_config import load_player_config

logger = logging.getLogger(__name__)

# Type alias for step functions
StepFn = Callable[[dict], dict | None]


def has_valid_body(comment: dict) -> dict | None:
    """
    Check if comment has a valid, non-empty body.

    Args:
        comment: Comment dictionary with optional 'body' field.

    Returns:
        Original comment if body is valid, None otherwise.
    """
    body = comment.get("body")
    if not body:
        return None
    if body in INVALID_BODY_VALUES:
        return None
    return comment


def extract_fields(comment: dict) -> dict:
    """
    Extract only the fields needed for downstream processing.

    Args:
        comment: Raw comment dictionary (may have many fields).

    Returns:
        Dictionary with only the REQUIRED_FIELDS needed for analysis.
    """
    return {field: comment.get(field) for field in REQUIRED_FIELDS}


class CommentPipeline:
    """
    Configurable pipeline for processing comments through filter steps.

    Tracks statistics for each step including total processed,
    accepted count, and per-step rejection counts.

    Example:
        pipeline = CommentPipeline()
        pipeline.add_step(is_target_subreddit)
        pipeline.add_step(has_valid_body)
        pipeline.add_step(extract_fields)

        for comment in comments:
            result = pipeline.process(comment)
            if result is not None:
                write(result)

        print(pipeline.stats)
        # {'total': 1000, 'accepted': 150, 'rejected_is_target_subreddit': 800, ...}
    """

    def __init__(self) -> None:
        """Initialize an empty pipeline with zeroed stats."""
        self._steps: list[tuple[str, StepFn]] = []
        self._stats: dict[str, int] = {
            "total": 0,
            "accepted": 0,
        }

    @property
    def stats(self) -> dict[str, int]:
        """
        Return processing statistics.

        Returns:
            Dict with 'total', 'accepted', and 'rejected_<step_name>' keys.
        """
        return self._stats.copy()

    def add_step(self, fn: StepFn, name: str | None = None) -> "CommentPipeline":
        """
        Add a processing step to the pipeline.

        Steps are executed in order. A step that returns None causes
        the comment to be rejected and counted against that step.

        Args:
            fn: Function taking dict, returning dict (pass) or None (reject).
            name: Optional step name for stats. Defaults to fn.__name__.

        Returns:
            Self, for method chaining.
        """
        step_name = name if name is not None else fn.__name__
        self._steps.append((step_name, fn))
        # Pre-initialize rejection counter for this step
        rejection_key = f"rejected_{step_name}"
        if rejection_key not in self._stats:
            self._stats[rejection_key] = 0
        return self

    def process(self, comment: dict) -> dict | None:
        """
        Process a single comment through all pipeline steps.

        Args:
            comment: Raw comment dictionary.

        Returns:
            Processed comment if all steps pass, None if rejected.
        """
        self._stats["total"] += 1
        current = comment

        for step_name, step_fn in self._steps:
            result = step_fn(current)
            if result is None:
                self._stats[f"rejected_{step_name}"] += 1
                return None
            current = result

        self._stats["accepted"] += 1
        return current

    def reset_stats(self) -> None:
        """Reset all statistics to zero."""
        for key in self._stats:
            self._stats[key] = 0


# -----------------------------------------------------------------------------
# Player mention matching
# -----------------------------------------------------------------------------

# Module-level lazy initialization (cached)
_player_patterns: tuple[dict, frozenset, dict] | None = None


def _get_player_patterns() -> tuple[dict, frozenset, dict]:
    """
    Load config and compile patterns once.

    Returns:
        Tuple of (players dict, short_aliases frozenset, compiled patterns dict).
    """
    global _player_patterns
    if _player_patterns is None:
        players, short_aliases = load_player_config()
        boundary_patterns = {
            alias: re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
            for alias in short_aliases
        }
        _player_patterns = (players, short_aliases, boundary_patterns)
    return _player_patterns


def find_player_mentions(text: str) -> list[str]:
    """
    Find all player mentions in text.

    Uses simple substring matching for most aliases, and word boundary
    matching for short aliases (like 'AD', 'Curry') to avoid false positives.

    Args:
        text: Text to search for player mentions.

    Returns:
        List of player names found (deduplicated).
    """
    if not text:
        return []

    players, short_aliases, patterns = _get_player_patterns()
    text_lower = text.lower()
    found = []

    for player, aliases in players.items():
        for alias in aliases:
            alias_lower = alias.lower()
            if alias_lower in short_aliases:
                # Use word boundary matching for short aliases
                if patterns[alias_lower].search(text):
                    found.append(player)
                    break
            else:
                # Simple substring match for longer aliases
                if alias_lower in text_lower:
                    found.append(player)
                    break

    return found


def filter_player_mentions(comment: dict) -> dict | None:
    """
    Filter to comments mentioning tracked players.

    StepFn-compatible: returns None if no mentions, otherwise
    returns comment with 'mentioned_players' field added.

    Args:
        comment: Comment dict with 'body' field.

    Returns:
        Comment with mentioned_players field, or None if no mentions.
    """
    body = comment.get("body", "")
    players = find_player_mentions(body)

    if not players:
        return None

    result = comment.copy()
    result["mentioned_players"] = players
    return result
