"""Cached data loading and shared helpers for the Streamlit dashboard.

This module is self-contained — no imports from the project-level utils/.
All pages import from here for data access, filtering, and formatting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# app/utils/data.py → app/utils/ → app/ → repo root
DATA_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "dashboard"
    / "aggregates.json"
)

SENTIMENT_COLORS: dict[str, str] = {
    "negative": "#E74C3C",
    "positive": "#2ECC71",
    "neutral": "#95A5A6",
}

METRIC_CONFIG: dict[str, dict[str, Any]] = {
    "Most Hated (Negative Rate)": {
        "column": "neg_rate",
        "ascending": False,
        "format": "rate",
    },
    "Most Loved (Positive Rate)": {
        "column": "pos_rate",
        "ascending": False,
        "format": "rate",
    },
    "Net Sentiment": {
        "column": "net_sentiment",
        "ascending": True,
        "format": "sentiment",
    },
    "Most Polarizing": {
        "column": "polarization",
        "ascending": False,
        "format": "rate",
    },
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


@st.cache_data
def load_data() -> dict[str, Any]:
    """Load aggregates.json once per session, returning DataFrames and dicts.

    Returns:
        Dict with keys:
            - player_overall: pd.DataFrame (111 rows)
            - player_team: pd.DataFrame (3,258 rows)
            - team_overall: pd.DataFrame (30 rows)
            - player_metadata: dict keyed by player name
            - metadata: dict of global stats
    """
    if not DATA_PATH.exists():
        st.error(
            f"Data file not found: {DATA_PATH}. "
            "Ensure aggregates.json is committed under data/dashboard/."
        )
        st.stop()

    with open(DATA_PATH) as f:
        raw = json.load(f)

    return {
        "player_overall": pd.DataFrame(raw["player_overall"]),
        "player_team": pd.DataFrame(raw["player_team"]),
        "team_overall": pd.DataFrame(raw["team_overall"]),
        "player_metadata": raw["player_metadata"],
        "metadata": raw["metadata"],
    }


# ---------------------------------------------------------------------------
# Filtering / enrichment
# ---------------------------------------------------------------------------


def filter_by_threshold(df: pd.DataFrame, threshold: int) -> pd.DataFrame:
    """Filter to rows where comment_count >= threshold.

    Args:
        df: DataFrame with a ``comment_count`` column.
        threshold: Minimum comment count.

    Returns:
        Filtered DataFrame.
    """
    return df[df["comment_count"] >= threshold].reset_index(drop=True)


def enrich_with_metadata(
    df: pd.DataFrame, player_metadata: dict[str, dict[str, Any]]
) -> pd.DataFrame:
    """Join team, conference, and headshot_url from player_metadata onto df.

    Args:
        df: DataFrame with an ``attributed_player`` column.
        player_metadata: Dict keyed by player name with team/conference/headshot_url.

    Returns:
        DataFrame with added team, conference, and headshot_url columns.
    """
    meta_df = pd.DataFrame.from_dict(player_metadata, orient="index")
    meta_df.index.name = "attributed_player"
    meta_df = meta_df.reset_index()

    cols_to_join = ["attributed_player", "team", "conference", "headshot_url"]
    available = [c for c in cols_to_join if c in meta_df.columns]

    return df.merge(meta_df[available], on="attributed_player", how="left")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_rate(value: float) -> str:
    """Format a 0-1 rate as a percentage string.

    Args:
        value: Rate between 0 and 1.

    Returns:
        Formatted string, e.g. ``"51.0%"``.
    """
    return f"{value * 100:.1f}%"


def format_sentiment(value: float) -> str:
    """Format a net sentiment value to 3 decimal places.

    Args:
        value: Sentiment score, typically between -1 and 1.

    Returns:
        Formatted string with sign, e.g. ``"-0.366"`` or ``"+0.145"``.
    """
    return f"{value:+.3f}"


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def get_player_rank(
    player: str,
    df: pd.DataFrame,
    metric: str,
    ascending: bool,
) -> int | None:
    """Compute a player's 1-indexed rank in a sorted DataFrame.

    Args:
        player: Player name to find.
        df: DataFrame with ``attributed_player`` and the metric column.
        metric: Column name to rank by.
        ascending: Sort direction (True = lowest first).

    Returns:
        1-indexed rank, or None if the player is not in df.
    """
    sorted_df = df.sort_values(metric, ascending=ascending).reset_index(drop=True)
    matches = sorted_df[sorted_df["attributed_player"] == player]
    if matches.empty:
        return None
    return int(matches.index[0]) + 1
