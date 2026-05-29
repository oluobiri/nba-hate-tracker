"""
Comment processing functions for validation, field extraction, and player matching.
"""

import logging
import re
from dataclasses import dataclass

from utils.constants import INVALID_BODY_VALUES, REQUIRED_FIELDS
from utils.player_config import load_player_config

logger = logging.getLogger(__name__)


@dataclass
class ProcessingStats:
    """Track processing statistics across validate/extract/match stages."""

    total_comments: int = 0
    accepted_comments: int = 0
    rejected_body: int = 0
    rejected_malformed: int = 0
    rejected_no_player_mention: int = 0

    @property
    def rejected_comments(self) -> int:
        """Total rejected comments (sum of all rejection reasons)."""
        return self.rejected_body + self.rejected_malformed + self.rejected_no_player_mention

    @property
    def acceptance_rate(self) -> float:
        """Fraction of total comments that were accepted."""
        if self.total_comments == 0:
            return 0.0
        return self.accepted_comments / self.total_comments

    def log_summary(self, logger: logging.Logger) -> None:
        """
        Log a formatted summary of processing statistics.

        Args:
            logger: Logger instance to write to.
        """
        logger.info("Total processed:              %s", f"{self.total_comments:,}")
        logger.info("Accepted:                     %s", f"{self.accepted_comments:,}")
        logger.info("Rejected (invalid body):      %s", f"{self.rejected_body:,}")
        logger.info("Rejected (malformed JSON):    %s", f"{self.rejected_malformed:,}")
        logger.info("Rejected (no player mention): %s", f"{self.rejected_no_player_mention:,}")
        if self.total_comments > 0:
            logger.info("Acceptance rate:              %s", f"{self.acceptance_rate:.2%}")


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
