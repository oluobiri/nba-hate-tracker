"""
NBA Stats API (stats.nba.com) acquisition via the nba_api package.

Source-named acquisition module: everything fetched from stats.nba.com
lives here — the season roster snapshot, the season game logs and
the per-game play-by-play archive.
Function-shaped rather than a client class — nba_api manages its own
HTTP per call, so there is no session state to hold.

stats.nba.com adds no retry handling of its own and its characteristic
failure mode is hanging; every endpoint call runs through a bounded
retry loop with exponential backoff.

Usage:
    from pipeline.nba_stats import fetch_rosters, fetch_team_game_log

    rosters = fetch_rosters("2025-26")
    team_log = fetch_team_game_log("2025-26")
"""

import logging
import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

import polars as pl
import requests
from nba_api.stats.endpoints import commonteamroster, leaguegamelog, playbyplayv3
from nba_api.stats.static import teams as static_teams

from pipeline.schemas import (
    PLAY_BY_PLAY_SCHEMA,
    PLAYER_GAME_LOG_SCHEMA,
    ROSTERS_SCHEMA,
    SCHEMA_VERSION,
    TEAM_GAME_LOG_SCHEMA,
    validate_schema,
)
from utils.constants import (
    NBA_STATS_CUP_SEASON_TYPE,
    NBA_STATS_GAME_LOG_SEASON_TYPES,
    NBA_STATS_MAX_ATTEMPTS,
    NBA_STATS_REQUEST_DELAY,
    NBA_STATS_RETRY_BACKOFF,
    NBA_STATS_TIMEOUT,
)
from utils.season_config import get_active_season

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


# Raw LeagueGameLog column -> snapshot column, the selection half of the
# two game-log schemas (team lines lack the PLAYER_* columns and player
# lines lack TEAM_NAME; the schema select drops what each does not use).
# Percentages, FANTASY_PTS and VIDEO_AVAILABLE are not selected.
_GAME_LOG_RENAME = {
    "GAME_ID": "game_id",
    "GAME_DATE": "game_date",
    "PLAYER_ID": "player_id",
    "PLAYER_NAME": "player_name",
    "TEAM_ID": "team_id",
    "TEAM_ABBREVIATION": "team_abbr",
    "TEAM_NAME": "team_name",
    "MATCHUP": "matchup",
    "WL": "wl",
    "MIN": "minutes",
    "FGM": "fgm",
    "FGA": "fga",
    "FG3M": "fg3m",
    "FG3A": "fg3a",
    "FTM": "ftm",
    "FTA": "fta",
    "OREB": "oreb",
    "DREB": "dreb",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "TOV": "tov",
    "PF": "pf",
    "PTS": "pts",
    "PLUS_MINUS": "plus_minus",
}

# Endpoint value of player_or_team_abbreviation -> (schema, grain key)
_GAME_LOG_KINDS = {
    "T": (TEAM_GAME_LOG_SCHEMA, "team_id"),
    "P": (PLAYER_GAME_LOG_SCHEMA, "player_id"),
}

# Play-by-play archive: files are written beside the target, then renamed,
# so a killed run never leaves a partial file that reads as banked.
_PLAY_BY_PLAY_TMP_SUFFIX = ".part"
_PLAY_BY_PLAY_PROGRESS_EVERY = 50

# Per-game failures that miss the game instead of stopping the run.
# ValueError covers an unparseable payload (JSONDecodeError) and a
# response that does not match PLAY_BY_PLAY_SCHEMA; KeyError covers a
# payload nba_api cannot unpack.
_PLAY_BY_PLAY_MISS_ERRORS = (requests.RequestException, ValueError, KeyError)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def check_snapshot_season(
    path: Path, *, subject: str, log: logging.Logger
) -> dict[str, str]:
    """
    Read a snapshot's file metadata and warn if its season stamp is off.

    Every snapshot this module's scripts write carries a `season` stamp;
    a snapshot fetched for another season is legitimate to read, just
    not silently. Warnings go to the caller's logger so they read as
    the consumer's own.

    Args:
        path: Snapshot parquet path.
        subject: What goes stale if the stamp is wrong, for the message.
        log: Logger to warn on.

    Returns:
        The snapshot's file metadata (season, fetched_at, ...).
    """
    stamps = pl.read_parquet_metadata(path)
    stamped = stamps.get("season")
    active = get_active_season()
    if stamped is None:
        log.warning(
            f"{path} carries no season stamp - snapshot lineage cannot be verified"
        )
    elif stamped != active:
        log.warning(
            f"{path}: season stamp {stamped!r} does not match active season "
            f"{active!r}; {subject} may be stale"
        )
    return stamps


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

    combined = pl.concat(frames, how="diagonal")
    rosters = (
        combined
        # nba_api serves "MAR 03, 1998"; titlecase so %b parses.
        .with_columns(
            pl.col("birth_date")
            .str.to_titlecase()
            .str.to_date("%b %d, %Y", strict=False)
        )
        .select(list(ROSTERS_SCHEMA.names()))
        .cast(dict(ROSTERS_SCHEMA))
    )
    # strict=False nulls unparseable dates silently; surface the ones the
    # parse nulled (as opposed to endpoint-supplied nulls) so a format
    # drift can't degrade the column while the run reports success.
    parse_failures = (
        rosters["birth_date"].null_count() - combined["birth_date"].null_count()
    )
    if parse_failures:
        logger.warning(
            f'{parse_failures} birth_date value(s) did not match "%b %d, %Y" '
            f"and were nulled"
        )
    logger.info(
        f"Fetched {rosters.height} players across "
        f"{rosters['team_abbr'].n_unique()} teams"
    )
    return rosters


def _fetch_game_log_page(
    season: str,
    season_type: str,
    player_or_team: str,
    timeout: int,
    schema: pl.Schema,
) -> pl.DataFrame:
    """
    Fetch one LeagueGameLog page, conformed to its game-log schema.

    Conforming per page (not after the union) is what lets an empty
    page — a play-in fetched mid-season — concatenate with the others:
    an empty pandas frame carries no dtypes of its own.

    Args:
        season: Season identifier the endpoint expects (e.g. "2025-26").
        season_type: Endpoint season-type label ("Regular Season", ...).
        player_or_team: "T" for team lines, "P" for player lines.
        timeout: Per-request timeout in seconds.
        schema: The game-log schema this page must conform to.

    Returns:
        Frame conforming to `schema`, season_type filled in.
    """
    raw = leaguegamelog.LeagueGameLog(
        season=season,
        season_type_all_star=season_type,
        player_or_team_abbreviation=player_or_team,
        timeout=timeout,
    ).get_data_frames()[0]
    cols = [c for c in _GAME_LOG_RENAME if c in raw.columns]
    selected = raw[cols].copy()
    # WL is null on a handful of lines; pandas "string" keeps NA as NA
    selected["WL"] = selected["WL"].astype("string")
    return (
        pl.from_pandas(selected)
        .rename({c: _GAME_LOG_RENAME[c] for c in cols})
        .with_columns(
            pl.lit(season_type).alias("season_type"),
            pl.col("game_date").cast(pl.String).str.to_date("%Y-%m-%d"),
        )
        .select(schema.names())
        .cast(dict(schema))
    )


def _fetch_game_log(
    season: str,
    player_or_team: str,
    *,
    delay: float,
    timeout: int,
    max_attempts: int,
    retry_backoff: float,
) -> pl.DataFrame:
    """
    Fetch a season's game log across every season type as one frame.

    The Cup ("IST") page re-lists the group-stage games already in the
    regular-season page; those re-listings are dropped so the Cup final
    is the only line left under "IST". Any other duplicate on the grain
    key is an endpoint fault and fails the fetch.

    Args:
        season: Season identifier (e.g. "2025-26").
        player_or_team: "T" for team lines, "P" for player lines.
        delay: Seconds to wait after each page request.
        timeout: Per-request timeout in seconds.
        max_attempts: Total attempts per page request (1 initial + retries).
        retry_backoff: Base seconds for exponential backoff between retries.

    Returns:
        One row per game x team ("T") or game x player ("P"), conforming
        to the matching game-log schema.

    Raises:
        requests.RequestException: If any page cannot be fetched.
        ValueError: If the log carries a duplicate outside the IST overlap.
    """
    schema, key = _GAME_LOG_KINDS[player_or_team]
    kind = "team" if player_or_team == "T" else "player"
    logger.info(f"Fetching {season} {kind} game log from stats.nba.com")

    pages: list[pl.DataFrame] = []
    for season_type in NBA_STATS_GAME_LOG_SEASON_TYPES:
        page = _call_with_retries(
            partial(
                _fetch_game_log_page,
                season,
                season_type,
                player_or_team,
                timeout,
                schema,
            ),
            label=f"{season_type} {kind} log",
            max_attempts=max_attempts,
            retry_backoff=retry_backoff,
        )
        logger.info(f"{season_type}: {page.height} {kind} lines")
        pages.append(page)
        time.sleep(delay)

    combined = pl.concat(pages)
    grain = ["game_id", key]
    is_cup = pl.col("season_type") == NBA_STATS_CUP_SEASON_TYPE
    others = combined.filter(~is_cup)
    cup_only = combined.filter(is_cup).join(others.select(grain), on=grain, how="anti")
    relisted = combined.filter(is_cup).height - cup_only.height
    logger.info(
        f"{NBA_STATS_CUP_SEASON_TYPE} re-listed {relisted} {kind} line(s) already "
        f"in the regular-season log; {cup_only.height} kept"
    )
    log = pl.concat([others, cup_only])

    duplicated = log.group_by(grain).len().filter(pl.col("len") > 1)
    if duplicated.height:
        raise ValueError(
            f"{kind} game log grain is one row per {' x '.join(grain)}; "
            f"duplicated: {duplicated.select(grain).head(10).rows()}"
        )

    return log.sort(["game_date", "game_id", key])


def fetch_team_game_log(
    season: str,
    *,
    delay: float = NBA_STATS_REQUEST_DELAY,
    timeout: int = NBA_STATS_TIMEOUT,
    max_attempts: int = NBA_STATS_MAX_ATTEMPTS,
    retry_backoff: float = NBA_STATS_RETRY_BACKOFF,
) -> pl.DataFrame:
    """
    Fetch a season's team lines, one row per game x team (TEAM_GAME_LOG_SCHEMA).

    Args:
        season: Season identifier (e.g. "2025-26").
        delay: Seconds to wait after each page request.
        timeout: Per-request timeout in seconds.
        max_attempts: Total attempts per page request (1 initial + retries).
        retry_backoff: Base seconds for exponential backoff between retries.

    Returns:
        Frame conforming to TEAM_GAME_LOG_SCHEMA.
    """
    return _fetch_game_log(
        season,
        "T",
        delay=delay,
        timeout=timeout,
        max_attempts=max_attempts,
        retry_backoff=retry_backoff,
    )


def fetch_player_game_log(
    season: str,
    *,
    delay: float = NBA_STATS_REQUEST_DELAY,
    timeout: int = NBA_STATS_TIMEOUT,
    max_attempts: int = NBA_STATS_MAX_ATTEMPTS,
    retry_backoff: float = NBA_STATS_RETRY_BACKOFF,
) -> pl.DataFrame:
    """
    Fetch a season's player lines, one row per game x player (PLAYER_GAME_LOG_SCHEMA).

    Every player who dressed is kept; the tracked-set selection happens
    at aggregation under the active players.yaml.

    Args:
        season: Season identifier (e.g. "2025-26").
        delay: Seconds to wait after each page request.
        timeout: Per-request timeout in seconds.
        max_attempts: Total attempts per page request (1 initial + retries).
        retry_backoff: Base seconds for exponential backoff between retries.

    Returns:
        Frame conforming to PLAYER_GAME_LOG_SCHEMA.
    """
    return _fetch_game_log(
        season,
        "P",
        delay=delay,
        timeout=timeout,
        max_attempts=max_attempts,
        retry_backoff=retry_backoff,
    )


# -----------------------------------------------------------------------------
# Play-by-play (PlayByPlayV3)
# -----------------------------------------------------------------------------


def _snake_case(name: str) -> str:
    """Convert an endpoint camelCase column name to snake_case ("playerNameI" -> "player_name_i")."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _fetch_play_by_play_frame(game_id: str, timeout: int) -> pl.DataFrame:
    """
    Fetch one game's actions and normalize them to snapshot column names.

    Every endpoint column is kept. Columns the schema knows are cast to
    its dtypes; a column it does not know (or one it misses) survives to
    fail validation at the write boundary, so endpoint drift is loud.

    Args:
        game_id: Ten-digit NBA game id.
        timeout: Per-request timeout in seconds.

    Returns:
        One row per action; zero rows for a game the endpoint does not know.
    """
    raw = playbyplayv3.PlayByPlayV3(game_id=game_id, timeout=timeout).get_data_frames()[
        0
    ]
    renamed = {col: _snake_case(col) for col in raw.columns}
    selected = raw.copy()
    for col, snake in renamed.items():
        if PLAY_BY_PLAY_SCHEMA.get(snake) == pl.String:
            # Scores are numeric-looking strings; a drift to raw JSON numbers
            # must not hand pl.from_pandas a mixed object column.
            selected[col] = selected[col].astype("string")
    frame = pl.from_pandas(selected).rename(renamed)
    return frame.cast(
        {
            col: PLAY_BY_PLAY_SCHEMA[col]
            for col in frame.columns
            if col in PLAY_BY_PLAY_SCHEMA
        }
    )


def fetch_play_by_play(
    game_id: str,
    *,
    timeout: int = NBA_STATS_TIMEOUT,
    max_attempts: int = NBA_STATS_MAX_ATTEMPTS,
    retry_backoff: float = NBA_STATS_RETRY_BACKOFF,
) -> pl.DataFrame:
    """
    Fetch one game's play-by-play, every action and column as served.

    Args:
        game_id: Ten-digit NBA game id.
        timeout: Per-request timeout in seconds.
        max_attempts: Total attempts (1 initial + retries).
        retry_backoff: Base seconds for exponential backoff between retries.

    Returns:
        One row per action, snake_cased; zero rows for an unknown game.

    Raises:
        requests.ConnectionError | requests.Timeout: After max_attempts.
        requests.RequestException | ValueError | KeyError: On a
            non-transient endpoint failure, without retries.
    """
    return _call_with_retries(
        partial(_fetch_play_by_play_frame, game_id, timeout),
        label=f"{game_id} play-by-play",
        max_attempts=max_attempts,
        retry_backoff=retry_backoff,
    )


@dataclass(frozen=True)
class PlayByPlayMiss:
    """One game a run could not bank.

    Attributes:
        game_id: The game's id.
        reason: What went wrong, for the report.
    """

    game_id: str
    reason: str


@dataclass
class PlayByPlayReport:
    """What an archive run banked, skipped and missed.

    Attributes:
        fetched: Game ids written this run.
        skipped: Game ids already banked on disk.
        misses: Every game that could not be banked.
    """

    fetched: list[str]
    skipped: list[str]
    misses: list[PlayByPlayMiss]

    @property
    def ok(self) -> bool:
        """True when nothing missed."""
        return not self.misses


def play_by_play_path(out_dir: Path, game_id: str) -> Path:
    """
    Path of one game's play-by-play snapshot.

    Args:
        out_dir: The season's play-by-play directory.
        game_id: Ten-digit NBA game id.

    Returns:
        out_dir / "<game_id>.parquet".
    """
    return out_dir / f"{game_id}.parquet"


def has_valid_play_by_play(path: Path) -> bool:
    """
    Whether a banked snapshot is present, readable, conforming and non-empty.

    Args:
        path: The snapshot's path.

    Returns:
        True when the file can be skipped on a resumed run.
    """
    if not path.exists():
        return False
    try:
        frame = pl.read_parquet(path)
        validate_schema(frame, PLAY_BY_PLAY_SCHEMA, path.name)
    except (OSError, ValueError, pl.exceptions.PolarsError):
        return False
    return frame.height > 0


def _write_parquet_atomic(
    frame: pl.DataFrame, path: Path, metadata: dict[str, str]
) -> None:
    """Write a parquet to a temp file beside the target, then replace."""
    tmp = path.with_name(path.name + _PLAY_BY_PLAY_TMP_SUFFIX)
    frame.write_parquet(tmp, metadata=metadata)
    os.replace(tmp, path)


def sync_play_by_play(
    game_ids: Iterable[str],
    out_dir: Path,
    *,
    season: str,
    delay: float = NBA_STATS_REQUEST_DELAY,
    timeout: int = NBA_STATS_TIMEOUT,
    max_attempts: int = NBA_STATS_MAX_ATTEMPTS,
    retry_backoff: float = NBA_STATS_RETRY_BACKOFF,
) -> PlayByPlayReport:
    """
    Bank one play-by-play snapshot per game, resuming from what is on disk.

    A game with a valid file is skipped, so a killed run restarts where it
    stopped. A game that serves zero actions, or fails in any per-game way
    once transient retries are spent, is a miss: logged, collected, and the
    run moves on.

    Args:
        game_ids: Games to bank, in fetch order.
        out_dir: The season's play-by-play directory.
        season: Season stamped into every file's metadata.
        delay: Seconds to wait after each request, misses included.
        timeout: Per-request timeout in seconds.
        max_attempts: Total attempts per game (1 initial + retries).
        retry_backoff: Base seconds for exponential backoff between retries.

    Returns:
        The report: what was fetched, skipped and missed.
    """
    game_ids = list(game_ids)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamps = {
        "season": season,
        "fetched_at": datetime.now(timezone.utc).date().isoformat(),
        "schema_version": str(SCHEMA_VERSION),
    }
    report = PlayByPlayReport(fetched=[], skipped=[], misses=[])

    for game_id in game_ids:
        path = play_by_play_path(out_dir, game_id)
        if has_valid_play_by_play(path):
            report.skipped.append(game_id)
            continue

        try:
            frame = fetch_play_by_play(
                game_id,
                timeout=timeout,
                max_attempts=max_attempts,
                retry_backoff=retry_backoff,
            )
            if frame.height == 0:
                raise ValueError("endpoint served zero actions")
            validate_schema(frame, PLAY_BY_PLAY_SCHEMA, path.name)
            _write_parquet_atomic(frame, path, stamps)
            report.fetched.append(game_id)
        except _PLAY_BY_PLAY_MISS_ERRORS as e:
            reason = f"{type(e).__name__}: {e}"
            logger.warning(f"Missed {game_id} - {reason}")
            report.misses.append(PlayByPlayMiss(game_id=game_id, reason=reason))
        time.sleep(delay)

        requested = len(report.fetched) + len(report.misses)
        if requested % _PLAY_BY_PLAY_PROGRESS_EVERY == 0:
            logger.info(
                f"{requested} requested ({len(report.fetched)} banked, "
                f"{len(report.misses)} missed), {len(report.skipped)} already on disk, "
                f"of {len(game_ids)}"
            )

    return report
