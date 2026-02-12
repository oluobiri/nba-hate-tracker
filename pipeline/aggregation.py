"""
Sentiment aggregation pipeline.

Transforms the classified sentiment parquet into precomputed JSON aggregates
for the Streamlit dashboard and animated bar race chart.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from utils.player_config import build_alias_to_player_map
from utils.team_config import build_alias_to_team_map

logger = logging.getLogger(__name__)


def resolve_player(
    mentioned_players: list[str] | None,
    sentiment_player: str | None,
    alias_map: dict[str, str],
) -> str | None:
    """
    Attribute a comment to a single canonical player.

    Uses four-bucket logic:
    1. Single player in mentioned_players → return it.
    2. Multi-player + sentiment_player is canonical → return as-is.
    3. Multi-player + sentiment_player normalizable via alias map → return canonical.
    4. Otherwise → return None.

    Args:
        mentioned_players: List of player names mentioned in the comment.
        sentiment_player: Player identified by sentiment classification.
        alias_map: Mapping of lowercase aliases to canonical player names.

    Returns:
        Canonical player name, or None if attribution fails.
    """
    if not mentioned_players:
        return None

    if len(mentioned_players) == 1:
        player = mentioned_players[0]
        return alias_map.get(player.lower(), player)

    # Multi-player: try to use sentiment_player for disambiguation
    if not sentiment_player:
        return None

    # Check if sentiment_player is already canonical
    if sentiment_player in alias_map.values():
        return sentiment_player

    # Try normalizing via alias map
    normalized = alias_map.get(sentiment_player.lower())
    return normalized


def extract_team_from_flair(
    flair_text: str | None,
    alias_to_team: dict[str, str],
) -> str | None:
    """
    Extract team name from Reddit flair text.

    Lowercases the flair and checks each team alias as a substring,
    trying longest aliases first to avoid collisions (e.g., "hornets"
    before "nets").

    Args:
        flair_text: Raw author flair text from Reddit.
        alias_to_team: Mapping of lowercase aliases to canonical team names.

    Returns:
        Canonical team name, or None if no match found.
    """
    if not flair_text:
        return None

    flair_lower = flair_text.lower()
    # Sort aliases longest-first to prevent substring collisions
    # (e.g., "hornets" must match before "nets")
    for alias in sorted(alias_to_team, key=len, reverse=True):
        if alias in flair_lower:
            return alias_to_team[alias]

    return None


def compute_metrics(df: pl.DataFrame, group_cols: list[str]) -> list[dict]:
    """
    Compute sentiment metrics grouped by specified columns.

    Calculates counts per sentiment, total comment count, rates,
    net sentiment, and polarization.

    Args:
        df: DataFrame with 'sentiment' column and group columns.
        group_cols: Columns to group by.

    Returns:
        List of dicts with group keys and computed metrics.
    """
    grouped = (
        df.group_by(group_cols)
        .agg(
            pl.col("sentiment").filter(pl.col("sentiment") == "neg").len().alias("neg_count"),
            pl.col("sentiment").filter(pl.col("sentiment") == "pos").len().alias("pos_count"),
            pl.col("sentiment").filter(pl.col("sentiment") == "neu").len().alias("neu_count"),
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
            (
                (pl.col("pos_count") - pl.col("neg_count")) / pl.col("comment_count")
            ).round(4).alias("net_sentiment"),
            (
                (pl.col("pos_count") + pl.col("neg_count")) / pl.col("comment_count")
            ).round(4).alias("polarization"),
        )
    )

    return grouped.to_dicts()


def aggregate_sentiment(input_path: Path) -> dict:
    """
    Aggregate classified sentiment data into dashboard-ready JSON.

    Reads the sentiment parquet, attributes comments to players,
    extracts team flair, and computes all aggregation views.

    Args:
        input_path: Path to sentiment.parquet file.

    Returns:
        Dict with keys: player_overall, player_temporal, player_team,
        team_overall, metadata.
    """
    logger.info(f"Loading sentiment data from {input_path}")
    df = pl.read_parquet(input_path)
    total_rows = len(df)
    logger.info(f"Loaded {total_rows:,} rows")

    # Filter out error rows
    df = df.filter(pl.col("sentiment") != "error")
    usable_rows = len(df)
    excluded_rows = total_rows - usable_rows
    logger.info(f"Usable rows: {usable_rows:,} (excluded {excluded_rows:,} errors)")

    # Build lookup maps
    alias_map = build_alias_to_player_map()
    team_map = build_alias_to_team_map()

    # Player attribution
    logger.info("Attributing comments to players...")
    df = df.with_columns(
        pl.struct(["mentioned_players", "sentiment_player"])
        .map_elements(
            lambda row: resolve_player(
                row["mentioned_players"],
                row["sentiment_player"],
                alias_map,
            ),
            return_dtype=pl.Utf8,
        )
        .alias("attributed_player")
    )

    attributed_count = df.filter(pl.col("attributed_player").is_not_null()).height
    logger.info(
        f"Attributed {attributed_count:,} / {usable_rows:,} "
        f"({attributed_count / usable_rows * 100:.1f}%)"
    )

    # Team flair extraction
    logger.info("Extracting team from flair...")
    df = df.with_columns(
        pl.col("author_flair_text")
        .map_elements(
            lambda flair: extract_team_from_flair(flair, team_map),
            return_dtype=pl.Utf8,
        )
        .alias("team")
    )

    team_count = df.filter(pl.col("team").is_not_null()).height
    logger.info(f"Matched {team_count:,} comments to team flairs")

    # Temporal prep: convert created_utc to datetime, truncate to week (Monday)
    df = df.with_columns(
        pl.from_epoch("created_utc")
        .dt.truncate("1w")
        .alias("week")
    )

    # --- Aggregation views ---

    # Player overall (attributed only)
    logger.info("Computing player_overall...")
    df_attributed = df.filter(pl.col("attributed_player").is_not_null())
    player_overall = compute_metrics(df_attributed, ["attributed_player"])
    player_overall.sort(key=lambda x: x["neg_rate"], reverse=True)

    # Player temporal (attributed only)
    logger.info("Computing player_temporal...")
    player_temporal = compute_metrics(df_attributed, ["attributed_player", "week"])

    # Player by team flair (both non-null)
    logger.info("Computing player_team...")
    df_player_team = df.filter(
        pl.col("attributed_player").is_not_null() & pl.col("team").is_not_null()
    )
    player_team = compute_metrics(df_player_team, ["attributed_player", "team"])

    # Team overall (team non-null)
    logger.info("Computing team_overall...")
    df_team = df.filter(pl.col("team").is_not_null())
    team_overall = compute_metrics(df_team, ["team"])

    # Metadata
    unique_players = df_attributed["attributed_player"].n_unique()
    unique_teams = df.filter(pl.col("team").is_not_null())["team"].n_unique()
    unique_weeks = df["week"].n_unique()

    metadata = {
        "total_comments": total_rows,
        "usable_comments": usable_rows,
        "excluded_comments": excluded_rows,
        "attributed_comments": attributed_count,
        "player_count": unique_players,
        "team_count": unique_teams,
        "week_count": unique_weeks,
        "season": "2024-25",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        f"Aggregation complete: {unique_players} players, "
        f"{unique_teams} teams, {unique_weeks} weeks"
    )

    return {
        "player_overall": player_overall,
        "player_temporal": player_temporal,
        "player_team": player_team,
        "team_overall": team_overall,
        "metadata": metadata,
    }
