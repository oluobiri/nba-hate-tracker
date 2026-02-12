"""
Tests for sentiment aggregation logic.

Tests cover the pure functions resolve_player, extract_team_from_flair,
and compute_metrics from the aggregation pipeline.
"""

import polars as pl

from pipeline.aggregation import compute_metrics, extract_team_from_flair, resolve_player


class TestResolvePlayer:
    """Tests for resolve_player function."""

    def test_single_player_returns_it(self, player_alias_map):
        """Single player in mentioned_players is returned directly."""
        result = resolve_player(
            ["LeBron James"], "Nikola Jokic", player_alias_map
        )
        assert result == "LeBron James"

    def test_single_player_normalizes_alias(self, player_alias_map):
        """Single non-canonical player name is normalized via alias map."""
        result = resolve_player(["jokic"], None, player_alias_map)
        assert result == "Nikola Jokic"

    def test_multi_player_canonical_sentiment_player(self, player_alias_map):
        """Multi-player with canonical sentiment_player returns it."""
        result = resolve_player(
            ["LeBron James", "Nikola Jokic"],
            "Nikola Jokic",
            player_alias_map,
        )
        assert result == "Nikola Jokic"

    def test_multi_player_alias_sentiment_player(self, player_alias_map):
        """Multi-player with alias sentiment_player normalizes to canonical."""
        result = resolve_player(
            ["LeBron James", "Nikola Jokic"],
            "jokic",
            player_alias_map,
        )
        assert result == "Nikola Jokic"

    def test_multi_player_null_sentiment_player(self, player_alias_map):
        """Multi-player with null sentiment_player returns None."""
        result = resolve_player(
            ["LeBron James", "Nikola Jokic"],
            None,
            player_alias_map,
        )
        assert result is None

    def test_multi_player_unrecognized_sentiment_player(self, player_alias_map):
        """Multi-player with unrecognized sentiment_player returns None."""
        result = resolve_player(
            ["LeBron James", "Nikola Jokic"],
            "unknown_player_xyz",
            player_alias_map,
        )
        assert result is None

    def test_empty_mentioned_players(self, player_alias_map):
        """Empty mentioned_players returns None."""
        result = resolve_player([], "LeBron James", player_alias_map)
        assert result is None

    def test_none_mentioned_players(self, player_alias_map):
        """None mentioned_players returns None."""
        result = resolve_player(None, "LeBron James", player_alias_map)
        assert result is None


class TestExtractTeamFromFlair:
    """Tests for extract_team_from_flair function."""

    def test_standard_flair(self, team_alias_map):
        """Standard Reddit flair with emoji prefix resolves."""
        result = extract_team_from_flair(":lal-1: Lakers", team_alias_map)
        assert result == "Los Angeles Lakers"

    def test_abbreviation_flair(self, team_alias_map):
        """Abbreviation-only flair resolves."""
        result = extract_team_from_flair(":bos-1:", team_alias_map)
        assert result == "Boston Celtics"

    def test_plain_text_flair(self, team_alias_map):
        """Plain text team name resolves."""
        result = extract_team_from_flair("Celtics", team_alias_map)
        assert result == "Boston Celtics"

    def test_null_flair(self, team_alias_map):
        """Null flair returns None."""
        result = extract_team_from_flair(None, team_alias_map)
        assert result is None

    def test_empty_flair(self, team_alias_map):
        """Empty string flair returns None."""
        result = extract_team_from_flair("", team_alias_map)
        assert result is None

    def test_unrecognized_flair(self, team_alias_map):
        """Unrecognized flair text returns None."""
        result = extract_team_from_flair(":AUS: Australia", team_alias_map)
        assert result is None

    def test_legacy_code_flair(self, team_alias_map):
        """Legacy Reddit flair code resolves."""
        result = extract_team_from_flair(":njn-1:", team_alias_map)
        assert result == "Brooklyn Nets"

    def test_substring_collision_hornets_not_nets(self, team_alias_map):
        """Hornets flair matches Charlotte, not Brooklyn (nets substring)."""
        result = extract_team_from_flair(":cha-1: Hornets", team_alias_map)
        assert result == "Charlotte Hornets"


class TestComputeMetrics:
    """Tests for compute_metrics function."""

    def test_basic_counts_and_rates(self):
        """Verify counts and rate calculations on synthetic data."""
        df = pl.DataFrame({
            "player": ["A", "A", "A", "A", "A", "B", "B", "B"],
            "sentiment": ["neg", "neg", "pos", "neu", "neu", "neg", "pos", "pos"],
        })

        results = compute_metrics(df, ["player"])
        results_by_player = {r["player"]: r for r in results}

        # Player A: 2 neg, 1 pos, 2 neu = 5 total
        a = results_by_player["A"]
        assert a["neg_count"] == 2
        assert a["pos_count"] == 1
        assert a["neu_count"] == 2
        assert a["comment_count"] == 5
        assert a["neg_rate"] == 0.4
        assert a["pos_rate"] == 0.2
        assert a["net_sentiment"] == -0.2
        assert a["polarization"] == 0.6

        # Player B: 1 neg, 2 pos, 0 neu = 3 total
        b = results_by_player["B"]
        assert b["neg_count"] == 1
        assert b["pos_count"] == 2
        assert b["neu_count"] == 0
        assert b["comment_count"] == 3

    def test_rates_rounded_to_four_decimals(self):
        """Rate values are rounded to 4 decimal places."""
        df = pl.DataFrame({
            "player": ["A", "A", "A"],
            "sentiment": ["neg", "pos", "pos"],
        })

        results = compute_metrics(df, ["player"])
        a = results[0]

        assert a["neg_rate"] == 0.3333
        assert a["pos_rate"] == 0.6667

    def test_multi_group_columns(self):
        """Grouping by multiple columns works."""
        df = pl.DataFrame({
            "player": ["A", "A", "B"],
            "team": ["LAL", "BOS", "LAL"],
            "sentiment": ["neg", "pos", "neu"],
        })

        results = compute_metrics(df, ["player", "team"])
        assert len(results) == 3
