"""
NBA Stats API (stats.nba.com) acquisition via the nba_api package.

Source-named acquisition module: everything fetched from stats.nba.com
lives here (v3 game data is the anticipated second caller). Function-
shaped rather than a client class — nba_api manages its own HTTP per
call, so there is no session state to hold.

stats.nba.com adds no retry handling of its own and its characteristic
failure mode is hanging; every endpoint call runs through a bounded
retry loop with exponential backoff.

Usage:
    from pipeline.nba_stats import fetch_rosters

    rosters = fetch_rosters("2025-26")
"""

import logging
import time
from collections.abc import Callable
from functools import partial

import polars as pl
import requests
from nba_api.stats.endpoints import commonteamroster
from nba_api.stats.static import teams as static_teams

from pipeline.schemas import ROSTERS_SCHEMA
from utils.constants import (
    NBA_STATS_MAX_ATTEMPTS,
    NBA_STATS_REQUEST_DELAY,
    NBA_STATS_RETRY_BACKOFF,
    NBA_STATS_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Raw endpoint column -> snapshot column. The selection half of
# ROSTERS_SCHEMA: endpoint columns absent here (SEASON, LeagueID,
# PLAYER_SLUG, TeamID) are dropped; team_name/team_abbr are added per
# team from the static team list, not the endpoint payload.
_RENAME = {
    "PLAYER_ID": "player_id",
    "PLAYER": "player_name",
    "NUM": "jersey_number",
    "POSITION": "position",
    "HEIGHT": "height",
    "WEIGHT": "weight",
    "AGE": "age",
    "EXP": "experience",
    "BIRTH_DATE": "birth_date",
    "SCHOOL": "school",
}

# Endpoint columns that must land as strings (birth_date included: it is
# parsed from string downstream). The endpoint serves these as strings
# today, but they are semantically numeric-ish (EXP "5"/"R", NUM "00"),
# so a serialization change to raw JSON numbers would hand pandas a
# mixed str/int object column that pl.from_pandas cannot convert —
# coercing in pandas first makes the fetch immune to that drift.
_STRING_SOURCE_COLUMNS = [
    raw
    for raw, col in _RENAME.items()
    if col == "birth_date" or ROSTERS_SCHEMA[col] == pl.String
]


def _call_with_retries(
    make_request: Callable[[], pl.DataFrame],
    *,
    label: str,
    max_attempts: int,
    retry_backoff: float,
) -> pl.DataFrame:
    """
    Run an endpoint call through a bounded retry loop.

    Connection errors and timeouts are transient by nature on
    stats.nba.com; anything else indicates a real problem with the
    request and propagates immediately.

    Args:
        make_request: Zero-arg callable performing one endpoint call.
        label: Human-readable request name for retry log lines.
        max_attempts: Total attempts (1 initial + retries).
        retry_backoff: Base seconds for exponential backoff between retries.

    Returns:
        The callable's result from the first successful attempt.

    Raises:
        requests.ConnectionError | requests.Timeout: The last transient
            error, after max_attempts is exhausted.
    """
    last_error: requests.RequestException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return make_request()
        except (requests.ConnectionError, requests.Timeout) as e:
            last_error = e
            if attempt < max_attempts:
                wait = retry_backoff * (2 ** (attempt - 1))
                logger.warning(
                    f"Transient stats.nba.com error on {label} "
                    f"(attempt {attempt}/{max_attempts}), retrying in {wait:.0f}s: {e}"
                )
                time.sleep(wait)

    raise last_error  # type: ignore[misc]  # loop always sets it before exiting


def _fetch_team_roster(team_id: int, season: str, timeout: int) -> pl.DataFrame:
    """
    Fetch one team's roster and normalize to snapshot column names.

    Args:
        team_id: nba_api static team id.
        season: Season identifier the endpoint expects (e.g. "2025-26").
        timeout: Per-request timeout in seconds.

    Returns:
        Frame with the renamed endpoint columns (team literals not yet added).
    """
    raw = commonteamroster.CommonTeamRoster(
        team_id=team_id, season=season, timeout=timeout
    ).get_data_frames()[0]
    cols = [c for c in _RENAME if c in raw.columns]
    selected = raw[cols].copy()
    for col in _STRING_SOURCE_COLUMNS:
        if col in selected.columns:
            # pandas "string" dtype stringifies elements but keeps NA as
            # NA (plain astype(str) would turn None into the string "None")
            selected[col] = selected[col].astype("string")
    return pl.from_pandas(selected).rename({c: _RENAME[c] for c in cols})


def fetch_rosters(
    season: str,
    *,
    delay: float = NBA_STATS_REQUEST_DELAY,
    timeout: int = NBA_STATS_TIMEOUT,
    max_attempts: int = NBA_STATS_MAX_ATTEMPTS,
    retry_backoff: float = NBA_STATS_RETRY_BACKOFF,
) -> pl.DataFrame:
    """
    Fetch all 30 team rosters for a season as one ROSTERS_SCHEMA frame.

    Strict by design: a team that exhausts its retries fails the whole
    fetch rather than producing a silently incomplete snapshot — the
    snapshot feeds the Player dimension, where a missing team would
    surface as unexplained join gaps.

    Args:
        season: Season identifier (e.g. "2025-26"). The CommonTeamRoster
            endpoint is season-parameterized, so past seasons are
            retro-fetchable.
        delay: Seconds to wait after each team request.
        timeout: Per-request timeout in seconds.
        max_attempts: Total attempts per team request (1 initial + retries).
        retry_backoff: Base seconds for exponential backoff between retries.

    Returns:
        One row per rostered player, conforming to ROSTERS_SCHEMA.

    Raises:
        requests.RequestException: If any team's roster cannot be fetched.
    """
    teams = static_teams.get_teams()
    logger.info(f"Fetching {len(teams)} team rosters for {season} from stats.nba.com")

    frames: list[pl.DataFrame] = []
    for team in teams:
        frame = _call_with_retries(
            partial(_fetch_team_roster, team["id"], season, timeout),
            label=f"{team['abbreviation']} roster",
            max_attempts=max_attempts,
            retry_backoff=retry_backoff,
        )
        frames.append(
            frame.with_columns(
                pl.lit(team["full_name"]).alias("team_name"),
                pl.lit(team["abbreviation"]).alias("team_abbr"),
            )
        )
        logger.debug(f"{team['abbreviation']}: {frame.height} players")
        time.sleep(delay)

    rosters = (
        pl.concat(frames, how="diagonal")
        # nba_api serves "MAR 03, 1998"; titlecase so %b parses.
        .with_columns(
            pl.col("birth_date")
            .str.to_titlecase()
            .str.to_date("%b %d, %Y", strict=False)
        )
        .select(list(ROSTERS_SCHEMA.names()))
        .cast(dict(ROSTERS_SCHEMA))
    )
    logger.info(
        f"Fetched {rosters.height} players across "
        f"{rosters['team_abbr'].n_unique()} teams"
    )
    return rosters
