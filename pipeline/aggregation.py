"""
Sentiment aggregation pipeline.

Transforms the classified sentiment parquet into precomputed JSON aggregates
for the Streamlit dashboard and animated bar race chart.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from pipeline.games import load_game_tables
from pipeline.nba_stats import check_snapshot_season
from pipeline.posts import load_posts_table
from pipeline.receipts import (
    build_comment_samples,
    load_receipt_verdicts,
    log_comment_samples_diagnostics,
)
from pipeline.schemas import (
    DASHBOARD_OUTPUT_SCHEMAS,
    GAME_SENTIMENT_SCHEMA,
    PLAYERS_CONFIG_COLUMNS,
    PLAYERS_SCHEMA,
    PLAYERS_SNAPSHOT_COLUMNS,
    SCHEMA_VERSION,
    SENTIMENT_SCHEMA,
    TEAM_OVERALL_SCHEMA,
    TEAMS_SCHEMA,
    validate_schema,
)
from utils.paths import get_reference_dir
from utils.player_config import (
    build_alias_to_player_map,
    load_player_config_version,
    load_player_metadata,
)
from utils.season_config import get_active_season
from utils.team_config import load_team_config, load_team_config_version

logger = logging.getLogger(__name__)


def compute_metrics(df: pl.DataFrame, group_cols: list[str]) -> pl.DataFrame:
    """
    Compute sentiment metrics grouped by specified columns.

    Calculates counts per sentiment, total comment count, rates,
    net sentiment, and polarization.

    Args:
        df: DataFrame with 'sentiment' column and group columns.
        group_cols: Columns to group by.

    Returns:
        DataFrame with group columns first, then count and rate columns,
        sorted by group_cols (group_by row order is nondeterministic).
    """
    grouped = (
        df.group_by(group_cols)
        .agg(
            pl.col("sentiment")
            .filter(pl.col("sentiment") == "neg")
            .len()
            .alias("neg_count"),
            pl.col("sentiment")
            .filter(pl.col("sentiment") == "pos")
            .len()
            .alias("pos_count"),
            pl.col("sentiment")
            .filter(pl.col("sentiment") == "neu")
            .len()
            .alias("neu_count"),
            pl.len().alias("comment_count"),
        )
        .with_columns(
            pl.col("neg_count").cast(pl.Int64),
            pl.col("pos_count").cast(pl.Int64),
            pl.col("neu_count").cast(pl.Int64),
            pl.col("comment_count").cast(pl.Int64),
        )
        .with_columns(
            (pl.col("neg_count") / pl.col("comment_count")).round(4).alias("neg_rate"),
            (pl.col("pos_count") / pl.col("comment_count")).round(4).alias("pos_rate"),
            ((pl.col("pos_count") - pl.col("neg_count")) / pl.col("comment_count"))
            .round(4)
            .alias("net_sentiment"),
            ((pl.col("pos_count") + pl.col("neg_count")) / pl.col("comment_count"))
            .round(4)
            .alias("polarization"),
        )
    )

    return grouped.sort(group_cols)


def compute_game_sentiment(df: pl.DataFrame, posts: pl.DataFrame) -> pl.DataFrame:
    """
    Roll the fact up to Player x Game through the Post bridge.

    A fact row reaches a game through its post (link_id = post_id ->
    game_id), so a game's threads (game + post-game) merge per game_id
    and a comment lands in at most one game. The measures cover the
    attributed rows; thread_comment_count is every usable fact row in
    the game's threads, whoever it mentions, repeated on each of the
    game's player rows. No floor: the display floor is a consumer choice.

    Args:
        df: Usable fact frame (SENTIMENT_SCHEMA plus week); attributed_player
            may be null.
        posts: Frame conforming to POSTS_SCHEMA.

    Returns:
        DataFrame conforming to GAME_SENTIMENT_SCHEMA, sorted by
        (attributed_player, game_id).
    """
    linked = df.join(
        posts.filter(pl.col("game_id").is_not_null()).select("post_id", "game_id"),
        left_on="link_id",
        right_on="post_id",
        how="inner",
    )
    room = linked.group_by("game_id").agg(
        pl.len().cast(pl.Int64).alias("thread_comment_count")
    )
    return (
        compute_metrics(
            linked.filter(pl.col("attributed_player").is_not_null()),
            ["attributed_player", "game_id"],
        )
        .join(room, on="game_id", how="left")
        .select(GAME_SENTIMENT_SCHEMA.names())
        .sort(["attributed_player", "game_id"])
    )


def _check_config_stamp(
    input_path: Path, metadata: dict[str, str], key: str, active: str, derived: str
) -> None:
    """Warn when a config-lineage stamp is missing or drifted from the active config."""
    stamped = metadata.get(key)
    if stamped is None:
        logger.warning(
            f"{input_path} carries no {key} stamp - config lineage of {derived} "
            f"cannot be verified"
        )
    elif stamped != active:
        logger.warning(
            f"{input_path}: {key} drift - parquet assembled with config "
            f"{stamped!r} but active config is {active!r}; {derived} may not "
            f"reflect the current config"
        )


def load_attributed_frame(input_path: Path) -> tuple[pl.DataFrame, int]:
    """
    Load the fact with its config-versioned attributes.

    Reads sentiment.parquet, validates it, warns on missing or drifted
    lineage stamps, drops error rows, and adds week. attributed_player
    and fan_team are read from the file, never recomputed here: they are
    materialized at assembly under the stamped configs, so every reader
    of the fact sees one resolution. This is the frame every consumer of
    the model starts from: the aggregate views, the receipts pool, and
    analysis.

    Args:
        input_path: Path to sentiment.parquet.

    Returns:
        Tuple of (frame with the week column added; count of error rows
        excluded).

    Raises:
        ValueError: If the input parquet does not match SENTIMENT_SCHEMA.
    """
    logger.info(f"Loading sentiment data from {input_path}")
    df = pl.read_parquet(input_path)
    validate_schema(df, SENTIMENT_SCHEMA, str(input_path))

    # Config-lineage checks: the derived columns reflect the configs the
    # parquet was assembled under; stale attribution is legitimate to
    # read, just not silently.
    parquet_metadata = pl.read_parquet_metadata(input_path)
    _check_config_stamp(
        input_path,
        parquet_metadata,
        "players_config_version",
        load_player_config_version(),
        "mentioned_players / attributed_player",
    )
    _check_config_stamp(
        input_path,
        parquet_metadata,
        "teams_config_version",
        load_team_config_version(),
        "fan_team",
    )

    # Classifier lineage: a birth certificate, not a cache stamp -
    # nothing live to drift against, so only absence is warnable.
    if (
        parquet_metadata.get("classifier_sentiment_model") is None
        or parquet_metadata.get("classifier_sentiment_prompt_version") is None
    ):
        logger.warning(
            f"{input_path} carries no classifier identity stamp - "
            f"classifier lineage cannot be verified"
        )

    total_rows = len(df)
    logger.info(f"Loaded {total_rows:,} rows")

    # Filter out error rows
    df = df.filter(pl.col("sentiment") != "error")
    usable_rows = len(df)
    excluded_rows = total_rows - usable_rows
    logger.info(f"Usable rows: {usable_rows:,} (excluded {excluded_rows:,} errors)")

    attributed_count = df.filter(pl.col("attributed_player").is_not_null()).height
    logger.info(
        f"Attributed {attributed_count:,} / {usable_rows:,} "
        f"({attributed_count / usable_rows * 100:.1f}%)"
    )
    team_count = df.filter(pl.col("fan_team").is_not_null()).height
    logger.info(f"Matched {team_count:,} comments to team flairs")

    # Temporal prep: convert created_utc to datetime, truncate to week (Monday)
    df = df.with_columns(pl.from_epoch("created_utc").dt.truncate("1w").alias("week"))

    return df, excluded_rows


def aggregate_sentiment(input_path: Path, targets_path: Path | None = None) -> dict:
    """
    Aggregate classified sentiment data into dashboard-ready JSON.

    Reads the sentiment parquet and computes all aggregation views. The
    comment samples are verified against the target-verifier sidecar
    when one exists and fall back to the gate-only rule when it doesn't;
    metadata says which (receipts_verified).

    Args:
        input_path: Path to sentiment.parquet file.
        targets_path: Path to sentiment_targets.parquet; None or a
            missing file selects the fallback posture.

    Returns:
        Dict where player_overall, player_temporal, player_team,
        team_overall, game_sentiment, players, teams, games, player_games,
        posts, and comment_samples hold pl.DataFrames conforming to
        DASHBOARD_OUTPUT_SCHEMAS; metadata is a dict. The legacy player_metadata dict is reconstructed at
        serialization time via players_to_metadata_dict().

    Raises:
        ValueError: If the input parquet does not match SENTIMENT_SCHEMA,
            or a computed output does not match its schema contract.
    """
    df, excluded_rows = load_attributed_frame(input_path)
    usable_rows = len(df)
    total_rows = usable_rows + excluded_rows
    attributed_count = df.filter(pl.col("attributed_player").is_not_null()).height
    player_metadata = load_player_metadata()
    team_config = load_team_config()

    # --- Aggregation views ---

    # Player overall (attributed only)
    logger.info("Computing player_overall...")
    df_attributed = df.filter(pl.col("attributed_player").is_not_null())
    player_overall = compute_metrics(df_attributed, ["attributed_player"]).sort(
        ["neg_rate", "attributed_player"], descending=[True, False]
    )

    # Player temporal (attributed only)
    logger.info("Computing player_temporal...")
    player_temporal = compute_metrics(df_attributed, ["attributed_player", "week"])

    # Player by team flair (both non-null). The views keep the unmarked
    # physical name "team" for the fan role until the contract rename.
    logger.info("Computing player_team...")
    df_player_team = df.filter(
        pl.col("attributed_player").is_not_null() & pl.col("fan_team").is_not_null()
    )
    player_team = compute_metrics(
        df_player_team, ["attributed_player", "fan_team"]
    ).rename({"fan_team": "team"})

    # Team overall (fan_team non-null)
    logger.info("Computing team_overall...")
    df_team = df.filter(pl.col("fan_team").is_not_null())

    # Team dimension: pure config export, also the single source for
    # team_overall's baked enrichment columns (abbreviation, conference,
    # logo_url) so the two can never drift.
    teams = build_teams_dimension(team_config)

    # Positive selection: the enrichment set is the intersection of the
    # two contracts, so a column added to the dimension alone never
    # propagates into the view. Left join appends the columns after the
    # metrics, matching TEAM_OVERALL_SCHEMA order; re-sort because joins
    # don't preserve row order.
    enrichment_cols = [c for c in TEAM_OVERALL_SCHEMA.names() if c in TEAMS_SCHEMA]
    team_overall = (
        compute_metrics(df_team, ["fan_team"])
        .rename({"fan_team": "team"})
        .join(teams.select(enrichment_cols), on="team", how="left")
        .sort("team")
    )

    # Metadata
    unique_players = df_attributed["attributed_player"].n_unique()
    unique_teams = df_team["fan_team"].n_unique()
    unique_weeks = df["week"].n_unique()

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "total_comments": total_rows,
        "usable_comments": usable_rows,
        "excluded_comments": excluded_rows,
        "attributed_comments": attributed_count,
        "player_count": unique_players,
        "team_count": unique_teams,
        "week_count": unique_weeks,
        "season": get_active_season(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Player dimension: config curation joined with snapshot facts, one
    # row per attributed player in players.yaml order
    attributed_players = set(player_overall.get_column("attributed_player").to_list())
    players = _build_players_dimension(player_metadata, attributed_players)

    # Game layer: the Game dimension and the attributed players' box-score
    # lines, derived from the season's game-log snapshots
    logger.info("Building games and player_games...")
    games, player_games, game_metadata = load_game_tables(
        get_reference_dir(), player_metadata, team_config, attributed_players
    )
    metadata.update(game_metadata)

    logger.info("Selecting comment_samples...")
    alias_map = build_alias_to_player_map()
    verdicts, receipts_metadata = load_receipt_verdicts(
        df_attributed, targets_path, alias_map
    )
    metadata.update(receipts_metadata)
    comment_samples = build_comment_samples(
        df_attributed, verdicts=verdicts, alias_map=alias_map
    )
    log_comment_samples_diagnostics(df_attributed, comment_samples)

    # Post bridge: the threads plus each receipt's post, from the bridge
    # scripts.process_posts derived against the same game-log snapshot
    logger.info("Selecting posts...")
    posts, posts_metadata = load_posts_table(
        get_reference_dir(), games, game_metadata["games_fetched_at"], comment_samples
    )
    metadata.update(posts_metadata)

    # Player x Game: the fact rolled up through the bridge
    logger.info("Computing game_sentiment...")
    game_sentiment = compute_game_sentiment(df, posts)
    logger.info(
        f"game_sentiment: {game_sentiment.height:,} player-game rows over "
        f"{game_sentiment['game_id'].n_unique():,} games"
    )

    logger.info(
        f"Aggregation complete: {unique_players} players, "
        f"{unique_teams} teams, {unique_weeks} weeks, "
        f"{comment_samples.height:,} comment samples"
    )

    outputs = {
        "player_overall": player_overall,
        "player_temporal": player_temporal,
        "player_team": player_team,
        "team_overall": team_overall,
        "game_sentiment": game_sentiment,
        "players": players,
        "teams": teams,
        "games": games,
        "player_games": player_games,
        "posts": posts,
        "comment_samples": comment_samples,
    }
    for name, schema in DASHBOARD_OUTPUT_SCHEMAS.items():
        validate_schema(outputs[name], schema, name)

    return {
        **outputs,
        "metadata": metadata,
    }


def build_teams_dimension(team_config: dict[str, dict]) -> pl.DataFrame:
    """
    Build the Team dimension: a pure export of config/teams.yaml.

    One row per franchise, in teams.yaml order. No fact dependency —
    every franchise ships regardless of which fan_teams the comments
    resolved to. Aliases stay config-only: the dimension describes and
    slices, it never selects.

    Args:
        team_config: Per-team config dict from load_team_config().

    Returns:
        Frame conforming to TEAMS_SCHEMA.
    """
    return pl.DataFrame(
        {
            "team": list(team_config),
            "abbreviation": [info["abbreviation"] for info in team_config.values()],
            "conference": [info["conference"] for info in team_config.values()],
            "team_id": [info["team_id"] for info in team_config.values()],
            "logo_url": [info["logo_url"] for info in team_config.values()],
        },
        schema=TEAMS_SCHEMA,
    )


def _build_players_dimension(
    player_metadata: dict[str, dict], attributed_players: set[str]
) -> pl.DataFrame:
    """
    Build the Player dimension: config curation joined with snapshot facts.

    Config side: one row per attributed player, in players.yaml order,
    with the roster team role-marked as roster_team. Snapshot side: LEFT
    JOIN on player_id from the season's rosters.parquet — a missing
    snapshot row (or the whole snapshot file) degrades to null snapshot
    columns, never dropped rows.

    Args:
        player_metadata: Per-player config dict from load_player_metadata().
        attributed_players: Players present in player_overall.

    Returns:
        Frame conforming to PLAYERS_SCHEMA.
    """
    config_rows = [
        {
            "attributed_player": player,
            "roster_team": meta.get("team"),
            "conference": meta.get("conference"),
            "player_id": meta.get("player_id"),
            "headshot_url": meta.get("headshot_url"),
        }
        for player, meta in player_metadata.items()
        if player in attributed_players
    ]
    config_side = pl.DataFrame(config_rows, schema=PLAYERS_CONFIG_COLUMNS)

    snapshot_path = get_reference_dir() / "rosters.parquet"
    if not snapshot_path.exists():
        logger.warning(
            f"{snapshot_path} not found (run scripts.fetch_rosters) - "
            f"snapshot columns will be null"
        )
        return config_side.with_columns(
            pl.lit(None, dtype=PLAYERS_SCHEMA[col]).alias(col)
            for col in PLAYERS_SNAPSHOT_COLUMNS
        )

    # Snapshot-lineage check, same spirit as the players_config_version
    # stamp: a snapshot fetched for another season is legitimate to read,
    # just not silently.
    check_snapshot_season(snapshot_path, subject="snapshot facts", log=logger)

    snapshot = pl.read_parquet(snapshot_path).select(
        ["player_id", *PLAYERS_SNAPSHOT_COLUMNS]
    )
    unmatched = config_side.join(snapshot, on="player_id", how="anti")
    if unmatched.height:
        logger.info(
            f"{unmatched.height} attributed player(s) missing from the roster "
            f"snapshot (snapshot columns null): "
            f"{unmatched['attributed_player'].to_list()}"
        )
    players = config_side.join(
        snapshot, on="player_id", how="left", maintain_order="left"
    )
    # Grain guard: a duplicate player_id in the snapshot would fan the LEFT
    # JOIN out to multiple rows per player - silent corruption downstream
    # (double-counted view joins, shim rows dropped by last-key-wins), so
    # it fails loudly here instead. validate_schema can't catch this: it
    # checks columns, not row grain.
    if players.height != config_side.height:
        duplicated = (
            snapshot.group_by("player_id")
            .len()
            .filter(pl.col("len") > 1)
            .get_column("player_id")
            .to_list()
        )
        raise ValueError(
            f"Player dimension fan-out: roster snapshot carries duplicate "
            f"player_id(s) {duplicated}; the dimension's grain is one row "
            f"per player - fix the snapshot (re-run scripts.fetch_rosters)"
        )
    return players


def players_to_metadata_dict(df: pl.DataFrame) -> dict[str, dict]:
    """
    Reconstruct the legacy aggregates.json player_metadata dict.

    Keys the dict by player name; values carry the config-side columns
    under their legacy JSON names (roster_team serializes as `team`).
    Snapshot columns don't ship in the JSON — the legacy consumers never
    knew them. Row order is preserved.

    Args:
        df: Player dimension frame conforming to PLAYERS_SCHEMA.

    Returns:
        Dict mapping player name to the legacy metadata fields, in
        frame-row order.
    """
    legacy_names = {
        col: ("team" if col == "roster_team" else col)
        for col in PLAYERS_CONFIG_COLUMNS
        if col != "attributed_player"
    }
    return {
        row["attributed_player"]: {
            legacy: row[col] for col, legacy in legacy_names.items()
        }
        for row in df.select(list(PLAYERS_CONFIG_COLUMNS)).iter_rows(named=True)
    }


# ---------------------------------------------------------------------------
# Bar race export helpers
# ---------------------------------------------------------------------------


def compute_cumulative_metrics(player_temporal: list[dict]) -> pl.DataFrame:
    """
    Compute running cumulative neg_rate for each player across weeks.

    Converts weekly snapshot counts into cumulative totals and rates.
    Excludes the final stub week (max date). Fills gaps so every player
    has a row for every week — missing weeks contribute zero new comments,
    keeping cumulative totals stable.

    Args:
        player_temporal: List of weekly metric dicts read back from
            aggregates.json, with week as a serialized string — not the
            in-memory DataFrame view returned by aggregate_sentiment().
            Each dict has: attributed_player, week, neg_count, comment_count.

    Returns:
        DataFrame with columns: attributed_player, week, cum_neg,
        cum_total, cum_neg_rate. Sorted by player then week.
    """
    df = pl.DataFrame(player_temporal)

    # Parse week strings to Date and exclude stub week
    df = df.with_columns(pl.col("week").str.to_datetime().cast(pl.Date))
    stub_week = df["week"].max()
    df = df.filter(pl.col("week") != stub_week)

    # Build complete player × week grid to fill gaps
    players = df.select("attributed_player").unique()
    weeks = df.select("week").unique()
    grid = players.join(weeks, how="cross")

    df = grid.join(
        df.select("attributed_player", "week", "neg_count", "comment_count"),
        on=["attributed_player", "week"],
        how="left",
    ).with_columns(
        pl.col("neg_count").fill_null(0),
        pl.col("comment_count").fill_null(0),
    )

    # Cumulative sums per player
    df = (
        df.sort("attributed_player", "week")
        .with_columns(
            pl.col("neg_count").cum_sum().over("attributed_player").alias("cum_neg"),
            pl.col("comment_count")
            .cum_sum()
            .over("attributed_player")
            .alias("cum_total"),
        )
        .with_columns(
            (pl.col("cum_neg").cast(pl.Int64) / pl.col("cum_total").cast(pl.Int64))
            .round(4)
            .alias("cum_neg_rate"),
        )
    )

    return df.select(
        "attributed_player", "week", "cum_neg", "cum_total", "cum_neg_rate"
    )


def mask_below_threshold(
    df: pl.DataFrame,
    min_comments: int = 1000,
) -> pl.DataFrame:
    """
    Replace cum_neg_rate with null where cumulative comments are below threshold.

    Flourish hides bars with empty cells, so masking low-volume weeks
    prevents noisy early-season rates from appearing in the animation.

    Args:
        df: DataFrame from compute_cumulative_metrics with cum_total
            and cum_neg_rate columns.
        min_comments: Minimum cumulative comment count to show a value.

    Returns:
        Same schema with cum_neg_rate set to null below threshold.
    """
    return df.with_columns(
        pl.when(pl.col("cum_total") >= min_comments)
        .then(pl.col("cum_neg_rate"))
        .otherwise(None)
        .alias("cum_neg_rate")
    )


def pivot_bar_race_wide(
    df: pl.DataFrame,
    player_metadata: dict[str, dict],
    top_n: int = 15,
    min_ranking_comments: int = 5000,
    min_entry_comments: int = 1000,
) -> pl.DataFrame:
    """
    Pivot cumulative metrics to Flourish bar-race-compatible wide format.

    Ranks players by their final-week cumulative neg_rate (before
    threshold masking), selects the top N, applies the entry mask,
    joins metadata (team and headshot), and pivots week dates into columns.

    Args:
        df: DataFrame from compute_cumulative_metrics with attributed_player,
            week, cum_neg, cum_total, and cum_neg_rate columns.
        player_metadata: Dict mapping player name to metadata with
            'team' and 'headshot_url' keys.
        top_n: Number of top players to include in the output.
        min_ranking_comments: Minimum cumulative comments in the final week
            for a player to qualify for top-N ranking. Excludes low-volume
            statistical outliers.
        min_entry_comments: Minimum cumulative comments for a player's bar
            to appear in a given week. Weeks below this get null (empty in
            CSV), causing Flourish to hide the bar.

    Returns:
        Wide-format DataFrame with columns: Label, Category, Image,
        and one column per week (ISO date string headers like '2024-10-07').
    """
    # Rank by final-week cum_neg_rate among players that have reached
    # the ranking threshold — excludes low-volume statistical outliers
    final_week = df["week"].max()
    final_rates = (
        df.filter(
            (pl.col("week") == final_week)
            & (pl.col("cum_total") >= min_ranking_comments)
        )
        .select("attributed_player", "cum_neg_rate")
        .sort("cum_neg_rate", descending=True)
    )
    top_players = final_rates.head(top_n)["attributed_player"].to_list()

    # Filter to top N players, then apply entry threshold mask
    df = df.filter(pl.col("attributed_player").is_in(top_players))
    df = mask_below_threshold(df, min_comments=min_entry_comments)

    # Format week as ISO date string for column headers
    df = df.with_columns(pl.col("week").cast(pl.Utf8))

    # Pivot to wide format
    wide = df.pivot(
        on="week",
        index="attributed_player",
        values="cum_neg_rate",
    )

    # Add metadata columns
    labels = wide["attributed_player"]
    categories = labels.map_elements(
        lambda p: player_metadata.get(p, {}).get("team", ""),
        return_dtype=pl.Utf8,
    )
    images = labels.map_elements(
        lambda p: player_metadata.get(p, {}).get("headshot_url", ""),
        return_dtype=pl.Utf8,
    )

    wide = wide.with_columns(
        labels.alias("Label"),
        categories.alias("Category"),
        images.alias("Image"),
    )

    # Reorder: Label, Category, Image, then week columns sorted chronologically
    week_cols = sorted(
        [
            c
            for c in wide.columns
            if c not in {"attributed_player", "Label", "Category", "Image"}
        ]
    )
    wide = wide.with_columns([(pl.col(c) * 100).round(2) for c in week_cols])
    wide = wide.select(["Label", "Category", "Image"] + week_cols)

    return wide
