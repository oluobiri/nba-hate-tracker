"""
Comment processing functions for validation, field extraction, and player matching.
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

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

    Returns None if no mentions, otherwise returns comment with
    'mentioned_players' field added.

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


def process_line(line: str, stats: ProcessingStats) -> dict | None:
    """
    Process a single JSON line through validate/extract/match pipeline.

    Args:
        line: Raw JSON string (one comment).
        stats: ProcessingStats object to update in place.

    Returns:
        Comment dict with mentioned_players if valid, None if rejected.
    """
    stats.total_comments += 1

    try:
        comment = json.loads(line)
    except json.JSONDecodeError:
        stats.rejected_malformed += 1
        return None

    if not has_valid_body(comment):
        stats.rejected_body += 1
        return None

    extracted = extract_fields(comment)

    result = filter_player_mentions(extracted)
    if result is None:
        stats.rejected_no_player_mention += 1
        return None

    stats.accepted_comments += 1
    return result


def read_last_created_utc(path: Path, tail_bytes: int = 65536) -> int | None:
    """
    Read the most recent created_utc from the tail of a raw JSONL file.

    Used to resume an interrupted download from where it stopped: the output
    file itself is the source of truth, so this survives any crash mode. Only
    the last tail_bytes are read (raw files are multi-GB), and lines are
    walked backward so a final line truncated by a mid-write kill is skipped
    in favor of the last complete one.

    Args:
        path: JSONL file of raw comments (one JSON object per line).
        tail_bytes: Bytes to read from the end of the file. Must comfortably
            exceed the longest expected line (~64x a typical comment).

    Returns:
        created_utc of the last parseable line, or None if the file is
        missing, empty, or has no parseable line in the tail window.
    """
    if not path.exists():
        return None

    file_size = path.stat().st_size
    if file_size == 0:
        return None

    with open(path, "rb") as f:
        f.seek(max(0, file_size - tail_bytes))
        tail = f.read().decode("utf-8", errors="replace")

    # split("\n"), not splitlines(): the latter also breaks on Unicode
    # separators (FS, LSEP, ...), which would misparse lines if the
    # writer ever emits them unescaped. The window's first line may be
    # partial (seek landed mid-line); walking backward naturally skips it.
    for line in reversed(tail.split("\n")):
        if not line.strip():
            continue
        try:
            comment = json.loads(line)
        except json.JSONDecodeError:
            continue
        created = comment.get("created_utc")
        if isinstance(created, (int, float)):
            return int(created)

    return None


def resume_after(path: Path, tail_bytes: int = 65536) -> int | None:
    """
    Resolve the resume cursor for a download output file.

    Fresh-start vs resume is decided by the file's actual state, not by
    whether a timestamp happened to parse: a non-empty file that yields no
    resume point raises instead of signaling a fresh start, which would
    let the caller truncate previously downloaded data.

    Args:
        path: JSONL output file of a previous download run.
        tail_bytes: Tail window passed to read_last_created_utc().

    Returns:
        The `after` cursor to resume from (last created_utc + 1, matching
        the pagination cursor's advance semantics), or None if the file is
        missing or empty (fresh start).

    Raises:
        ValueError: If the file has content but no parseable resume point
            in the tail window.
    """
    if not path.exists() or path.stat().st_size == 0:
        return None

    last_ts = read_last_created_utc(path, tail_bytes)
    if last_ts is None:
        raise ValueError(
            f"{path} has data but no parseable resume point in its last "
            f"{tail_bytes} bytes; refusing to overwrite it. Inspect the "
            "file, or rerun with --force to start fresh."
        )

    return last_ts + 1


def ensure_trailing_newline(path: Path) -> bool:
    """
    Ensure a file ends with a newline before records are appended to it.

    A crash can leave a truncated final line with no trailing newline;
    appending directly would fuse the next record onto it, corrupting
    both. The orphaned partial line is rejected downstream as malformed
    JSON instead.

    Args:
        path: File about to be appended to.

    Returns:
        True if a newline was appended, False if none was needed.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False

    with open(path, "rb") as f:
        f.seek(-1, 2)
        if f.read(1) == b"\n":
            return False

    with open(path, "a") as f:
        f.write("\n")
    return True
