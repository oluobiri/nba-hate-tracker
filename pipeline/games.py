"""
The game layer: games.parquet and player_games.parquet.

Derives the Game dimension and the per-player box-score lines from the
season game-log snapshots (pipeline/nba_stats.py) under the active
config: team abbreviations resolve to canonical Team names through
teams.yaml, player lines to canonical players through players.yaml
player_id. The snapshots hold every game and every player; this module
decides what ships.
"""

import logging
from pathlib import Path

import polars as pl

from pipeline.nba_stats import check_snapshot_season
from pipeline.schemas import GAMES_SCHEMA, PLAYER_GAMES_SCHEMA

logger = logging.getLogger(__name__)

TEAM_GAME_LOG_FILENAME = "team_game_log.parquet"
PLAYER_GAME_LOG_FILENAME = "player_game_log.parquet"

# The game id's three-digit prefix encodes the season type; it is the one
# decoder for season_type, the Cup final and the preseason. The endpoint
# label carried on the snapshot is provenance, not an input.
GAME_ID_PREFIX_SEASON_TYPES = {
    "001": "pre_season",
    "002": "regular_season",
    "004": "playoffs",
    "005": "play_in",
    "006": "regular_season",  # the NBA Cup final: its own id, regular-season window
}
PRE_SEASON_PREFIX = "001"
PLAYOFF_PREFIX = "004"
NBA_CUP_FINAL_PREFIX = "006"

# "BOS vs. NYK" is Boston at home; "BOS @ NYK" is Boston away.
_HOME_MARKER = " vs. "
_OPPONENT_PATTERN = r"(?:vs\.|@)\s*(\S+)$"


def build_games(team_log: pl.DataFrame, abbr_to_team: dict[str, str]) -> pl.DataFrame:
    """
    Pivot the team game log into the Game dimension, one row per game.

    Games against non-NBA opponents (an abbreviation unknown to
    teams.yaml, preseason only) are dropped with a logged count. On a
    neutral-site game both lines read "@"; sides are then assigned by
    team_id so the row is independent of endpoint order. The winner is
    the higher score; W/L is checked against it, never trusted alone.

    Args:
        team_log: Frame conforming to TEAM_GAME_LOG_SCHEMA.
        abbr_to_team: Team abbreviation -> canonical name, from teams.yaml.

    Returns:
        Frame conforming to GAMES_SCHEMA, sorted by date then id.

    Raises:
        ValueError: If a game id has an unknown prefix, a non-preseason
            game involves an unknown abbreviation, a game has a row count
            other than two, a matchup is null or names two hosts, or a
            game's W/L is missing or disagrees with its scores.
    """
    prefix = pl.col("game_id").str.slice(0, 3)
    unknown_prefix = team_log.filter(~prefix.is_in(list(GAME_ID_PREFIX_SEASON_TYPES)))
    if unknown_prefix.height:
        raise ValueError(
            "team_game_log carries game id prefix(es) with no season type: "
            f"{sorted(unknown_prefix.select(prefix.alias('p'))['p'].unique().to_list())}"
        )

    log = team_log.with_columns(
        pl.col("team_abbr").replace_strict(abbr_to_team, default=None).alias("team")
    )
    unknown = log.filter(pl.col("team").is_null())
    if unknown.height:
        not_preseason = unknown.filter(prefix != PRE_SEASON_PREFIX)
        if not_preseason.height:
            raise ValueError(
                "team_game_log carries abbreviation(s) unknown to teams.yaml "
                f"outside the preseason: "
                f"{sorted(not_preseason['team_abbr'].unique().to_list())}"
            )
        dropped_ids = unknown["game_id"].unique().to_list()
        logger.info(
            f"Dropped {len(dropped_ids)} preseason game(s) against non-NBA "
            f"opponents: {sorted(unknown['team_abbr'].unique().to_list())}"
        )
        log = log.filter(~pl.col("game_id").is_in(dropped_ids))

    malformed = log.group_by("game_id").len().filter(pl.col("len") != 2)
    if malformed.height:
        raise ValueError(
            "team_game_log grain is one row per game x team, two per game; "
            f"{malformed.height} game(s) break it: "
            f"{malformed.sort('game_id').head(10).rows()}"
        )
    no_matchup = log.filter(pl.col("matchup").is_null())
    if no_matchup.height:
        raise ValueError(
            f"team_game_log has null matchup on {no_matchup['game_id'].to_list()[:10]}"
        )

    # Within a game, sort so the home row leads: (is_home desc, team_id
    # desc). A neutral-site game has two equal is_home values and falls
    # through to team_id, which is what makes the assignment stable.
    ordered = (
        log.with_columns(
            pl.col("matchup").str.contains(_HOME_MARKER, literal=True).alias("is_home")
        )
        .sort(["game_id", "is_home", "team_id"], descending=[False, True, True])
        .group_by("game_id", maintain_order=True)
        .agg(
            pl.col("game_date").first(),
            pl.col("is_home").sum().alias("home_rows"),
            pl.col("team").first().alias("home_team"),
            pl.col("team").last().alias("away_team"),
            pl.col("pts").first().alias("home_score"),
            pl.col("pts").last().alias("away_score"),
            pl.col("wl").first().alias("home_wl"),
        )
    )

    two_hosts = ordered.filter(pl.col("home_rows") > 1)
    if two_hosts.height:
        raise ValueError(
            f"team_game_log lists both teams as host on {two_hosts['game_id'].to_list()[:10]}"
        )
    home_won = pl.col("home_score") > pl.col("away_score")
    inconsistent = ordered.filter(
        pl.col("home_wl").is_null() | ((pl.col("home_wl") == "W") != home_won)
    )
    if inconsistent.height:
        raise ValueError(
            f"team_game_log W/L is missing or disagrees with the scores on "
            f"{inconsistent['game_id'].to_list()[:10]}"
        )

    is_playoff = prefix == PLAYOFF_PREFIX
    games = (
        ordered.with_columns(
            prefix.replace_strict(GAME_ID_PREFIX_SEASON_TYPES).alias("season_type"),
            (prefix == NBA_CUP_FINAL_PREFIX).alias("nba_cup_final"),
            (pl.col("home_rows") == 0).alias("neutral_site"),
            pl.when(home_won)
            .then(pl.col("home_team"))
            .otherwise(pl.col("away_team"))
            .alias("winner"),
            pl.when(is_playoff)
            .then(pl.col("game_id").str.slice(7, 1).cast(pl.Int64))
            .alias("playoff_round"),
            pl.when(is_playoff)
            .then(pl.col("game_id").str.slice(8, 1).cast(pl.Int64))
            .alias("playoff_series"),
            pl.when(is_playoff)
            .then(pl.col("game_id").str.slice(9, 1).cast(pl.Int64))
            .alias("playoff_game"),
        )
        .select(GAMES_SCHEMA.names())
        .cast(dict(GAMES_SCHEMA))
        .sort(["game_date", "game_id"])
    )

    by_type = games.group_by("season_type").len().sort("season_type")
    logger.info(
        f"games: {games.height} rows "
        f"({', '.join(f'{t} {n}' for t, n in by_type.rows())}); "
        f"{games['neutral_site'].sum()} neutral-site"
    )
    return games


def build_player_games(
    player_log: pl.DataFrame,
    games: pl.DataFrame,
    player_metadata: dict[str, dict],
    abbr_to_team: dict[str, str],
    attributed_players: set[str],
) -> pl.DataFrame:
    """
    Select and label the box-score lines of the attributed players.

    Lines are kept only for games present in `games` (so a dropped game
    takes its lines with it) and for players in the Player dimension,
    joined on player_id. `roster_team` and `opponent` resolve to canonical
    names; is_home is derived from games.home_team, and is null on a
    neutral-site game, where neither side hosted.

    Args:
        player_log: Frame conforming to PLAYER_GAME_LOG_SCHEMA.
        games: Frame conforming to GAMES_SCHEMA.
        player_metadata: Per-player config dict from load_player_metadata().
        abbr_to_team: Team abbreviation -> canonical name, from teams.yaml.
        attributed_players: Players present in the Player dimension.

    Returns:
        Frame conforming to PLAYER_GAMES_SCHEMA, sorted by game then player.

    Raises:
        ValueError: If a player appears twice in one game.
    """
    id_to_player = {
        meta["player_id"]: player
        for player, meta in player_metadata.items()
        if player in attributed_players and meta.get("player_id") is not None
    }

    lines = (
        player_log.filter(pl.col("player_id").is_in(list(id_to_player)))
        .join(
            games.select("game_id", "home_team", "neutral_site"),
            on="game_id",
            how="inner",
        )
        .with_columns(
            pl.col("player_id").replace_strict(id_to_player).alias("attributed_player"),
            pl.col("team_abbr").replace_strict(abbr_to_team).alias("roster_team"),
            pl.col("matchup")
            .str.extract(_OPPONENT_PATTERN, 1)
            .replace_strict(abbr_to_team)
            .alias("opponent"),
        )
        .with_columns(
            pl.when(pl.col("neutral_site"))
            .then(pl.lit(None, dtype=pl.Boolean))
            .otherwise(pl.col("roster_team") == pl.col("home_team"))
            .alias("is_home")
        )
    )

    duplicated = (
        lines.group_by(["game_id", "player_id"]).len().filter(pl.col("len") > 1)
    )
    if duplicated.height:
        raise ValueError(
            "player_game_log grain is one row per game x player; duplicated: "
            f"{duplicated.select('game_id', 'player_id').head(10).rows()}"
        )

    player_games = (
        lines.select(PLAYER_GAMES_SCHEMA.names())
        .cast(dict(PLAYER_GAMES_SCHEMA))
        .sort(["game_id", "attributed_player"])
    )

    with_lines = set(player_games["attributed_player"].unique().to_list())
    without = sorted(set(id_to_player.values()) - with_lines)
    movers = (
        player_games.group_by("attributed_player")
        .agg(pl.col("roster_team").n_unique().alias("teams"))
        .filter(pl.col("teams") > 1)
        .height
    )
    logger.info(
        f"player_games: {player_games.height} lines for {len(with_lines)} of "
        f"{len(id_to_player)} attributed players; {movers} played for more "
        f"than one team"
    )
    if without:
        logger.info(f"Attributed players with no game lines: {without}")
    return player_games


def load_game_tables(
    reference_dir: Path,
    player_metadata: dict[str, dict],
    team_config: dict[str, dict],
    attributed_players: set[str],
) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    """
    Build games and player_games from the season's game-log snapshots.

    A missing snapshot degrades to empty tables with a warning, so
    aggregation stays runnable before scripts.fetch_games has run for
    the season. Both snapshots' season stamps are checked, and a fetch
    date that differs between them is flagged: the two logs are one
    fetch, and a fresh team log beside a stale player log joins to
    nothing without complaint otherwise.

    Args:
        reference_dir: Season reference directory holding the snapshots.
        player_metadata: Per-player config dict from load_player_metadata().
        team_config: Team config dict from load_team_config().
        attributed_players: Players present in the Player dimension.

    Returns:
        (games, player_games, metadata) where metadata carries game_count,
        player_game_count and games_fetched_at (the snapshot's stamp, or
        None when absent).
    """
    team_path = reference_dir / TEAM_GAME_LOG_FILENAME
    player_path = reference_dir / PLAYER_GAME_LOG_FILENAME
    missing = [p for p in (team_path, player_path) if not p.exists()]
    if missing:
        logger.warning(
            f"{[str(p) for p in missing]} not found (run scripts.fetch_games) - "
            f"games and player_games will be empty"
        )
        games = pl.DataFrame(schema=GAMES_SCHEMA)
        player_games = pl.DataFrame(schema=PLAYER_GAMES_SCHEMA)
        fetched_at = None
    else:
        team_stamps = check_snapshot_season(team_path, subject="game data", log=logger)
        player_stamps = check_snapshot_season(
            player_path, subject="game data", log=logger
        )
        fetched_at = team_stamps.get("fetched_at")
        if fetched_at != player_stamps.get("fetched_at"):
            logger.warning(
                f"{team_path} and {player_path} carry different fetch dates "
                f"({fetched_at!r} vs {player_stamps.get('fetched_at')!r}); "
                f"re-run scripts.fetch_games so both logs come from one fetch"
            )
        abbr_to_team = {
            info["abbreviation"]: team for team, info in team_config.items()
        }
        games = build_games(pl.read_parquet(team_path), abbr_to_team)
        player_games = build_player_games(
            pl.read_parquet(player_path),
            games,
            player_metadata,
            abbr_to_team,
            attributed_players,
        )

    metadata = {
        "game_count": games.height,
        "player_game_count": player_games.height,
        "games_fetched_at": fetched_at,
    }
    return games, player_games, metadata
