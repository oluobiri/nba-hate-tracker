"""
The Post bridge: posts_bridge.parquet and posts.parquet.

Derives post_type and game_id for every r/NBA post from its flair and
title under the active config: title spellings resolve to canonical
Team names through teams.yaml, and the title's team pair plus the
Eastern-time day of created_utc resolve to a game through the Game
dimension. The raw posts file holds every post; this module decides
what ships.
"""

import logging
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import polars as pl

logger = logging.getLogger(__name__)

RAW_POSTS_FILENAME = "r_nba_posts.jsonl"
POSTS_BRIDGE_FILENAME = "posts_bridge.parquet"

GAME_THREAD = "game_thread"
POST_GAME_THREAD = "post_game_thread"
OTHER = "other"
POST_TYPES = (GAME_THREAD, POST_GAME_THREAD, OTHER)
FLAIR_POST_TYPES = {"Game Thread": GAME_THREAD, "Post Game Thread": POST_GAME_THREAD}

# Threads follow the US schedule, so a post's calendar day is Eastern.
# A game thread is posted on the game's day; a post-game thread on the
# same day or, after a late West-coast tip, the next; the mods' titles
# sometimes carry the UTC day, one off either way.
POST_LOCAL_TZ = ZoneInfo("America/New_York")
GAME_DATE_WINDOW_DAYS = (-1, 0, 1)

# Title fallback for flair-stripped (mod-removed) threads. Anchored, so
# the daily "... + Game Thread Index" posts never match.
_TITLE_POST_TYPES = (
    (re.compile(r"^\[?\s*game thread\b", re.IGNORECASE), GAME_THREAD),
    (re.compile(r"^\[?\s*post[- ]?game thread\b", re.IGNORECASE), POST_GAME_THREAD),
)
# "(October 04, 2025)" on the mods' threads, "| Apr 28, 2026" on the bots'.
_TITLE_DATE = re.compile(r"\b([A-Z][a-z]{2,8} \d{1,2}, \d{4})\b")
_TITLE_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y")
# A (W-L) record looks like a score; strip records before reading one.
_RECORD = re.compile(r"\(\d+-\d+\)")
_SCORE = re.compile(r"(?<!\d)(\d{2,3})\s*[-–]\s*(\d{2,3})(?!\d)")


def classify_post(title: str, flair: str | None) -> str:
    """
    Derive post_type from the post's flair, falling back to its title.

    The two thread flairs decide outright, and any other flair is
    `other` whatever the title says (the daily index post carries
    "Game Thread" mid-title). Only a post with no flair at all — the
    mods strip it when they remove a duplicate — is classified by an
    anchored title prefix.

    Args:
        title: Post title.
        flair: link_flair_text, None when unflaired.

    Returns:
        One of POST_TYPES.
    """
    if flair is not None:
        return FLAIR_POST_TYPES.get(flair, OTHER)
    for pattern, post_type in _TITLE_POST_TYPES:
        if pattern.match(title):
            return post_type
    return OTHER


def build_title_name_map(team_config: dict[str, dict]) -> dict[str, str]:
    """
    Map the spellings a title may use for a team to its canonical name.

    Canonical names plus the multi-word entries of teams.yaml aliases[]
    (the flair fragments), lowercased. Single-token aliases are left
    out: `was` and `tor` sit inside ordinary words of a post-game
    title, and an abbreviation never appears in one.

    Args:
        team_config: Team config dict from load_team_config().

    Returns:
        Lowercased spelling -> canonical team name.
    """
    name_map = {team.lower(): team for team in team_config}
    for team, info in team_config.items():
        for alias in info.get("aliases", []):
            if " " in alias:
                name_map[alias.lower()] = team
    return name_map


def extract_team_pair(title: str, name_map: dict[str, str]) -> frozenset[str] | None:
    """
    Find the two teams a thread title names, as an unordered pair.

    Spellings are matched longest-first on word boundaries and consumed
    as they match, so "Portland Trail Blazers" is never also read as
    "Trail Blazers". The pair is unordered because the three game-thread
    title formats disagree on which side is listed first.

    Args:
        title: Post title.
        name_map: Spelling -> canonical name, from build_title_name_map().

    Returns:
        The two canonical names, or None when the title names fewer
        than two distinct teams (non-games, non-NBA opponents).
    """
    remaining = title.lower()
    found: list[str] = []
    for spelling in sorted(name_map, key=len, reverse=True):
        pattern = rf"(?<![a-z0-9]){re.escape(spelling)}(?![a-z0-9])"
        remaining, hits = re.subn(pattern, " ", remaining)
        if hits and name_map[spelling] not in found:
            found.append(name_map[spelling])
    if len(found) < 2:
        return None
    return frozenset(found[:2])


def parse_title_date(title: str) -> date | None:
    """
    Read a "Month DD, YYYY" date out of a thread title, if it carries one.

    Args:
        title: Post title.

    Returns:
        The date, or None when the title has no such date.
    """
    match = _TITLE_DATE.search(title)
    if match is None:
        return None
    for fmt in _TITLE_DATE_FORMATS:
        try:
            return datetime.strptime(match.group(1), fmt).date()
        except ValueError:
            continue
    return None


def parse_score(title: str) -> set[int] | None:
    """
    Read the final score out of a post-game title, as an unordered set.

    Args:
        title: Post title.

    Returns:
        The two scores, or None when the title carries none.
    """
    match = _SCORE.search(_RECORD.sub("", title))
    if match is None:
        return None
    return {int(match.group(1)), int(match.group(2))}


def local_date(created_utc: int) -> date:
    """
    The Eastern calendar day of a UTC epoch timestamp.

    Args:
        created_utc: Epoch seconds.

    Returns:
        The date in POST_LOCAL_TZ.
    """
    return (
        datetime.fromtimestamp(created_utc, tz=timezone.utc)
        .astimezone(POST_LOCAL_TZ)
        .date()
    )


def build_game_index(
    games: pl.DataFrame,
) -> dict[tuple[frozenset[str], date], list[dict]]:
    """
    Index the Game dimension by (unordered team pair, game date).

    Args:
        games: Frame conforming to GAMES_SCHEMA.

    Returns:
        (pair, game_date) -> the game rows on that day (one, barring a
        doubleheader), each with game_id, game_date and both scores.
    """
    index: dict[tuple[frozenset[str], date], list[dict]] = {}
    for row in games.select(
        "game_id", "game_date", "home_team", "away_team", "home_score", "away_score"
    ).iter_rows(named=True):
        key = (frozenset({row["home_team"], row["away_team"]}), row["game_date"])
        index.setdefault(key, []).append(row)
    return index


def match_game(
    pair: frozenset[str],
    created_utc: int,
    title_date: date | None,
    score: set[int] | None,
    index: dict[tuple[frozenset[str], date], list[dict]],
) -> str | None:
    """
    Resolve a thread to the game it is about.

    Candidates are the pair's games within a day either side of the
    thread's Eastern creation day. More than one (a back-to-back) is
    narrowed by the title date, then the score, then the creation day
    itself; a tie that survives all three is left unlinked and logged.

    Args:
        pair: The two teams the title names.
        created_utc: The post's creation time, epoch seconds.
        title_date: A date read from the title, or None.
        score: The score read from the title, or None.
        index: From build_game_index().

    Returns:
        The game_id, or None when no game or no single game fits.
    """
    created_day = local_date(created_utc)
    candidates = [
        game
        for days in GAME_DATE_WINDOW_DAYS
        for game in index.get((pair, created_day + timedelta(days=days)), [])
    ]
    for narrow in (
        lambda g: title_date is not None and g["game_date"] == title_date,
        lambda g: score is not None and {g["home_score"], g["away_score"]} == score,
        lambda g: g["game_date"] == created_day,
    ):
        if len(candidates) < 2:
            break
        candidates = [g for g in candidates if narrow(g)] or candidates
    if len(candidates) == 1:
        return candidates[0]["game_id"]
    if candidates:
        logger.warning(
            f"Ambiguous game for {sorted(pair)} around {created_day}: "
            f"{[g['game_id'] for g in candidates]}; left unlinked"
        )
    return None
