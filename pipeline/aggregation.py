"""
Sentiment aggregation pipeline.

Transforms the classified sentiment parquet into precomputed JSON aggregates
for the Streamlit dashboard and animated bar race chart.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from utils.player_config import build_alias_to_player_map, load_player_metadata
from utils.team_config import build_alias_to_team_map, load_team_config

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
    player_metadata = load_player_metadata()
    team_config = load_team_config()

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

    # Add conference field to each team row
    for row in team_overall:
        team_info = team_config.get(row["team"], {})
        row["conference"] = team_info.get("conference")

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

    # Filter player metadata to only players in player_overall
    attributed_players = {row["attributed_player"] for row in player_overall}
    filtered_player_metadata = {
        player: meta
        for player, meta in player_metadata.items()
        if player in attributed_players
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
        "player_metadata": filtered_player_metadata,
        "metadata": metadata,
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
        player_temporal: List of weekly metric dicts from aggregates.json.
            Each dict has: attributed_player, week, neg_count, comment_count.

    Returns:
        DataFrame with columns: attributed_player, week, cum_neg,
        cum_total, cum_neg_rate. Sorted by player then week.
    """
    df = pl.DataFrame(player_temporal)

    # Parse week strings to Date and exclude stub week
    df = df.with_columns(
        pl.col("week").str.to_datetime().cast(pl.Date)
    )
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

    return df.select("attributed_player", "week", "cum_neg", "cum_total", "cum_neg_rate")


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
        [c for c in wide.columns if c not in {"attributed_player", "Label", "Category", "Image"}]
    )
    wide = wide.select(["Label", "Category", "Image"] + week_cols)

    return wide
