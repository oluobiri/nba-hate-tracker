"""Tests for app/utils/data.py — dashboard data loading and helpers.

Tests pure functions only (no Streamlit dependency). Uses small fixture
DataFrames (5 players) with no dependency on the real data file.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.utils.data import (
    enrich_with_metadata,
    filter_by_threshold,
    format_rate,
    format_sentiment,
    get_player_rank,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_player_df() -> pd.DataFrame:
    """Five-player DataFrame mimicking player_overall schema."""
    return pd.DataFrame(
        [
            {
                "attributed_player": "Player A",
                "neg_rate": 0.51,
                "pos_rate": 0.14,
                "net_sentiment": -0.37,
                "polarization": 0.65,
                "comment_count": 50000,
            },
            {
                "attributed_player": "Player B",
                "neg_rate": 0.49,
                "pos_rate": 0.19,
                "net_sentiment": -0.30,
                "polarization": 0.68,
                "comment_count": 30000,
            },
            {
                "attributed_player": "Player C",
                "neg_rate": 0.35,
                "pos_rate": 0.25,
                "net_sentiment": -0.10,
                "polarization": 0.60,
                "comment_count": 8000,
            },
            {
                "attributed_player": "Player D",
                "neg_rate": 0.30,
                "pos_rate": 0.30,
                "net_sentiment": 0.00,
                "polarization": 0.60,
                "comment_count": 3000,
            },
            {
                "attributed_player": "Player E",
                "neg_rate": 0.20,
                "pos_rate": 0.40,
                "net_sentiment": 0.20,
                "polarization": 0.60,
                "comment_count": 500,
            },
        ]
    )


@pytest.fixture()
def sample_metadata() -> dict[str, dict]:
    """Player metadata dict for the five fixture players."""
    return {
        "Player A": {
            "team": "Team Alpha",
            "conference": "East",
            "player_id": 1,
            "headshot_url": "https://example.com/a.png",
            "logo_url": "https://example.com/logo_a.svg",
        },
        "Player B": {
            "team": "Team Beta",
            "conference": "West",
            "player_id": 2,
            "headshot_url": "https://example.com/b.png",
            "logo_url": "https://example.com/logo_b.svg",
        },
        "Player C": {
            "team": "Team Gamma",
            "conference": "East",
            "player_id": 3,
            "headshot_url": "https://example.com/c.png",
            "logo_url": "https://example.com/logo_c.svg",
        },
        "Player D": {
            "team": "Team Delta",
            "conference": "West",
            "player_id": 4,
            "headshot_url": "https://example.com/d.png",
            "logo_url": "https://example.com/logo_d.svg",
        },
        "Player E": {
            "team": "Team Epsilon",
            "conference": "East",
            "player_id": 5,
            "headshot_url": "https://example.com/e.png",
            "logo_url": "https://example.com/logo_e.svg",
        },
    }


# ---------------------------------------------------------------------------
# TestFormatRate
# ---------------------------------------------------------------------------


class TestFormatRate:
    """Tests for format_rate — converts 0-1 float to percentage string."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0.5105, "51.0%"),
            (0.0, "0.0%"),
            (1.0, "100.0%"),
            (0.0674, "6.7%"),
            (0.9999, "100.0%"),
        ],
        ids=["typical", "zero", "one", "small", "near_one"],
    )
    def test_format_rate(self, value: float, expected: str) -> None:
        """Verify rate formatting for various inputs."""
        assert format_rate(value) == expected


# ---------------------------------------------------------------------------
# TestFormatSentiment
# ---------------------------------------------------------------------------


class TestFormatSentiment:
    """Tests for format_sentiment — formats net sentiment with sign."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (-0.3659, "-0.366"),
            (0.145, "+0.145"),
            (0.0, "+0.000"),
            (-1.0, "-1.000"),
            (1.0, "+1.000"),
        ],
        ids=["negative", "positive", "zero", "min", "max"],
    )
    def test_format_sentiment(self, value: float, expected: str) -> None:
        """Verify sentiment formatting for various inputs."""
        assert format_sentiment(value) == expected


# ---------------------------------------------------------------------------
# TestFilterByThreshold
# ---------------------------------------------------------------------------


class TestFilterByThreshold:
    """Tests for filter_by_threshold — filters by minimum comment count."""

    def test_low_threshold_keeps_all(self, sample_player_df: pd.DataFrame) -> None:
        """A threshold below the smallest count keeps all rows."""
        # Arrange
        threshold = 100

        # Act
        result = filter_by_threshold(sample_player_df, threshold)

        # Assert
        assert len(result) == 5

    def test_medium_threshold(self, sample_player_df: pd.DataFrame) -> None:
        """A medium threshold filters out low-volume players."""
        # Arrange
        threshold = 5000

        # Act
        result = filter_by_threshold(sample_player_df, threshold)

        # Assert
        assert len(result) == 3
        assert set(result["attributed_player"]) == {
            "Player A",
            "Player B",
            "Player C",
        }

    def test_high_threshold_returns_empty(
        self, sample_player_df: pd.DataFrame
    ) -> None:
        """A threshold above all counts returns an empty DataFrame."""
        # Arrange
        threshold = 100_000

        # Act
        result = filter_by_threshold(sample_player_df, threshold)

        # Assert
        assert len(result) == 0
        assert list(result.columns) == list(sample_player_df.columns)

    def test_resets_index(self, sample_player_df: pd.DataFrame) -> None:
        """Filtered result has a clean 0-based index."""
        # Arrange / Act
        result = filter_by_threshold(sample_player_df, 5000)

        # Assert
        assert list(result.index) == [0, 1, 2]


# ---------------------------------------------------------------------------
# TestGetPlayerRank
# ---------------------------------------------------------------------------


class TestGetPlayerRank:
    """Tests for get_player_rank — computes 1-indexed rank in sorted df."""

    def test_top_player_descending(self, sample_player_df: pd.DataFrame) -> None:
        """The player with highest neg_rate is rank 1 when descending."""
        # Arrange / Act
        rank = get_player_rank(
            "Player A", sample_player_df, "neg_rate", ascending=False
        )

        # Assert
        assert rank == 1

    def test_second_player(self, sample_player_df: pd.DataFrame) -> None:
        """The second highest neg_rate player is rank 2."""
        rank = get_player_rank(
            "Player B", sample_player_df, "neg_rate", ascending=False
        )
        assert rank == 2

    def test_ascending_sort(self, sample_player_df: pd.DataFrame) -> None:
        """Net sentiment ascending puts most negative first."""
        rank = get_player_rank(
            "Player A", sample_player_df, "net_sentiment", ascending=True
        )
        assert rank == 1

    def test_player_not_in_df(self, sample_player_df: pd.DataFrame) -> None:
        """A player not in the DataFrame returns None."""
        rank = get_player_rank(
            "Unknown Player", sample_player_df, "neg_rate", ascending=False
        )
        assert rank is None

    def test_filtered_df(self, sample_player_df: pd.DataFrame) -> None:
        """Rank changes when the DataFrame is pre-filtered."""
        # Arrange — filter to 5K+ only (A, B, C)
        filtered = filter_by_threshold(sample_player_df, 5000)

        # Act
        rank = get_player_rank("Player C", filtered, "neg_rate", ascending=False)

        # Assert — C is 3rd among filtered players
        assert rank == 3

    def test_player_below_threshold_returns_none(
        self, sample_player_df: pd.DataFrame
    ) -> None:
        """A player filtered out by threshold is not found."""
        filtered = filter_by_threshold(sample_player_df, 5000)
        rank = get_player_rank("Player E", filtered, "neg_rate", ascending=False)
        assert rank is None


# ---------------------------------------------------------------------------
# TestEnrichWithMetadata
# ---------------------------------------------------------------------------


class TestEnrichWithMetadata:
    """Tests for enrich_with_metadata — joins team/conference/headshot."""

    def test_adds_expected_columns(
        self,
        sample_player_df: pd.DataFrame,
        sample_metadata: dict,
    ) -> None:
        """Enrichment adds team, conference, and headshot_url columns."""
        # Arrange / Act
        result = enrich_with_metadata(sample_player_df, sample_metadata)

        # Assert
        assert "team" in result.columns
        assert "conference" in result.columns
        assert "headshot_url" in result.columns

    def test_correct_values(
        self,
        sample_player_df: pd.DataFrame,
        sample_metadata: dict,
    ) -> None:
        """Joined values match the metadata dict."""
        # Arrange / Act
        result = enrich_with_metadata(sample_player_df, sample_metadata)
        player_a = result[result["attributed_player"] == "Player A"].iloc[0]

        # Assert
        assert player_a["team"] == "Team Alpha"
        assert player_a["conference"] == "East"
        assert player_a["headshot_url"] == "https://example.com/a.png"

    def test_preserves_original_columns(
        self,
        sample_player_df: pd.DataFrame,
        sample_metadata: dict,
    ) -> None:
        """Original DataFrame columns are preserved after enrichment."""
        result = enrich_with_metadata(sample_player_df, sample_metadata)
        for col in sample_player_df.columns:
            assert col in result.columns

    def test_row_count_unchanged(
        self,
        sample_player_df: pd.DataFrame,
        sample_metadata: dict,
    ) -> None:
        """Row count is unchanged after enrichment (left join)."""
        result = enrich_with_metadata(sample_player_df, sample_metadata)
        assert len(result) == len(sample_player_df)
