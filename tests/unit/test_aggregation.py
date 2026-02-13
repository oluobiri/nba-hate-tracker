"""
Tests for sentiment aggregation logic.

Tests cover the pure functions resolve_player, extract_team_from_flair,
and compute_metrics from the aggregation pipeline.
"""

import polars as pl

from pipeline.aggregation import (
    aggregate_sentiment,
    compute_cumulative_metrics,
    compute_metrics,
    extract_team_from_flair,
    mask_below_threshold,
    pivot_bar_race_wide,
    resolve_player,
)


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


def _make_test_parquet(tmp_path, rows):
    """Create a minimal sentiment parquet for testing aggregate_sentiment."""
    df = pl.DataFrame(rows)
    path = tmp_path / "test_sentiment.parquet"
    df.write_parquet(path)
    return path


class TestAggregatePlayerMetadata:
    """Tests for player_metadata key in aggregate output."""

    def test_player_metadata_key_exists(self, tmp_path):
        """Output contains player_metadata top-level key."""
        path = _make_test_parquet(tmp_path, {
            "comment_id": ["c1", "c2"],
            "body": ["LeBron is great", "LeBron is washed"],
            "author": ["u1", "u2"],
            "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
            "author_flair_css_class": ["lakers", "celtics"],
            "created_utc": [1704067200, 1704153600],
            "score": [10, 5],
            "mentioned_players": [["LeBron James"], ["LeBron James"]],
            "sentiment": ["pos", "neg"],
            "confidence": [0.9, 0.8],
            "sentiment_player": ["LeBron James", "LeBron James"],
            "input_tokens": [100, 100],
            "output_tokens": [20, 20],
        })

        result = aggregate_sentiment(path)

        assert "player_metadata" in result
        assert isinstance(result["player_metadata"], dict)

    def test_metadata_contains_attributed_players(self, tmp_path):
        """player_metadata includes metadata for attributed players."""
        path = _make_test_parquet(tmp_path, {
            "comment_id": ["c1", "c2"],
            "body": ["LeBron is great", "LeBron is washed"],
            "author": ["u1", "u2"],
            "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
            "author_flair_css_class": ["lakers", "celtics"],
            "created_utc": [1704067200, 1704153600],
            "score": [10, 5],
            "mentioned_players": [["LeBron James"], ["LeBron James"]],
            "sentiment": ["pos", "neg"],
            "confidence": [0.9, 0.8],
            "sentiment_player": ["LeBron James", "LeBron James"],
            "input_tokens": [100, 100],
            "output_tokens": [20, 20],
        })

        result = aggregate_sentiment(path)
        meta = result["player_metadata"]

        assert "LeBron James" in meta
        assert meta["LeBron James"]["team"] == "Los Angeles Lakers"
        assert meta["LeBron James"]["conference"] == "West"
        assert meta["LeBron James"]["player_id"] == 2544

    def test_metadata_excludes_non_attributed_players(self, tmp_path):
        """player_metadata only includes players that appear in player_overall."""
        path = _make_test_parquet(tmp_path, {
            "comment_id": ["c1"],
            "body": ["LeBron is great"],
            "author": ["u1"],
            "author_flair_text": [":lal-1: Lakers"],
            "author_flair_css_class": ["lakers"],
            "created_utc": [1704067200],
            "score": [10],
            "mentioned_players": [["LeBron James"]],
            "sentiment": ["pos"],
            "confidence": [0.9],
            "sentiment_player": ["LeBron James"],
            "input_tokens": [100],
            "output_tokens": [20],
        })

        result = aggregate_sentiment(path)
        meta = result["player_metadata"]

        # Only LeBron attributed — Giannis should not be in metadata
        assert "LeBron James" in meta
        assert "Giannis Antetokounmpo" not in meta


class TestAggregateTeamConference:
    """Tests for conference field in team_overall rows."""

    def test_team_overall_has_conference(self, tmp_path):
        """Each team_overall row has a conference field."""
        path = _make_test_parquet(tmp_path, {
            "comment_id": ["c1", "c2"],
            "body": ["Go team", "Nice game"],
            "author": ["u1", "u2"],
            "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
            "author_flair_css_class": ["lakers", "celtics"],
            "created_utc": [1704067200, 1704153600],
            "score": [10, 5],
            "mentioned_players": [[], []],
            "sentiment": ["pos", "neu"],
            "confidence": [0.9, 0.7],
            "sentiment_player": [None, None],
            "input_tokens": [100, 100],
            "output_tokens": [20, 20],
        })

        result = aggregate_sentiment(path)

        for row in result["team_overall"]:
            assert "conference" in row, f"Missing conference for {row['team']}"

    def test_conference_values_correct(self, tmp_path):
        """Conference values match expected East/West assignments."""
        path = _make_test_parquet(tmp_path, {
            "comment_id": ["c1", "c2"],
            "body": ["Go team", "Nice game"],
            "author": ["u1", "u2"],
            "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
            "author_flair_css_class": ["lakers", "celtics"],
            "created_utc": [1704067200, 1704153600],
            "score": [10, 5],
            "mentioned_players": [[], []],
            "sentiment": ["pos", "neu"],
            "confidence": [0.9, 0.7],
            "sentiment_player": [None, None],
            "input_tokens": [100, 100],
            "output_tokens": [20, 20],
        })

        result = aggregate_sentiment(path)
        team_by_name = {r["team"]: r for r in result["team_overall"]}

        assert team_by_name["Los Angeles Lakers"]["conference"] == "West"
        assert team_by_name["Boston Celtics"]["conference"] == "East"


# ---------------------------------------------------------------------------
# Bar race export tests
# ---------------------------------------------------------------------------


def _make_temporal_records(
    players_weeks: dict[str, list[tuple[str, int, int]]],
) -> list[dict]:
    """Build player_temporal-shaped dicts for testing.

    Args:
        players_weeks: Mapping of player name to list of
            (week_str, neg_count, comment_count) tuples.

    Returns:
        List of dicts matching the player_temporal schema.
    """
    records = []
    for player, weeks in players_weeks.items():
        for week_str, neg, total in weeks:
            records.append({
                "attributed_player": player,
                "week": week_str,
                "neg_count": neg,
                "pos_count": total - neg,
                "neu_count": 0,
                "comment_count": total,
                "neg_rate": round(neg / total, 4) if total else 0,
                "pos_rate": round((total - neg) / total, 4) if total else 0,
                "net_sentiment": 0.0,
                "polarization": 0.0,
            })
    return records


class TestComputeCumulativeMetrics:
    """Tests for compute_cumulative_metrics function."""

    def test_excludes_stub_week(self):
        """The maximum week (stub) is excluded from the output."""
        records = _make_temporal_records({
            "Player A": [
                ("2024-10-07 00:00:00", 5, 50),
                ("2024-10-14 00:00:00", 10, 100),
                ("2024-10-21 00:00:00", 2, 10),  # stub (max week)
            ],
        })
        result = compute_cumulative_metrics(records)
        weeks = result["week"].to_list()
        from datetime import date
        assert date(2024, 10, 21) not in weeks
        assert len(weeks) == 2

    def test_cumulative_sums_correct(self):
        """Running neg and total counts accumulate across weeks."""
        records = _make_temporal_records({
            "Player A": [
                ("2024-10-07 00:00:00", 5, 50),
                ("2024-10-14 00:00:00", 10, 100),
                ("2024-10-21 00:00:00", 1, 10),  # stub
            ],
        })
        result = compute_cumulative_metrics(records)
        rows = result.sort("week").to_dicts()

        assert rows[0]["cum_neg"] == 5
        assert rows[0]["cum_total"] == 50
        assert rows[1]["cum_neg"] == 15
        assert rows[1]["cum_total"] == 150

    def test_fills_missing_weeks(self):
        """A player missing from a week gets zero new counts, cumulative carries forward."""
        records = _make_temporal_records({
            "Player A": [
                ("2024-10-07 00:00:00", 5, 50),
                # gap at 2024-10-14
                ("2024-10-21 00:00:00", 10, 100),
                ("2024-10-28 00:00:00", 1, 10),  # stub
            ],
            "Player B": [
                ("2024-10-07 00:00:00", 3, 30),
                ("2024-10-14 00:00:00", 7, 70),
                ("2024-10-21 00:00:00", 2, 20),
                ("2024-10-28 00:00:00", 1, 10),  # stub
            ],
        })
        result = compute_cumulative_metrics(records)
        a_rows = result.filter(
            pl.col("attributed_player") == "Player A"
        ).sort("week").to_dicts()

        # Player A has 3 rows (all non-stub weeks)
        assert len(a_rows) == 3
        # Week 2 (gap): cumulative should equal week 1 values
        assert a_rows[1]["cum_neg"] == 5
        assert a_rows[1]["cum_total"] == 50
        # Week 3: adds actual data
        assert a_rows[2]["cum_neg"] == 15
        assert a_rows[2]["cum_total"] == 150

    def test_cum_neg_rate_rounded(self):
        """Cumulative neg_rate is rounded to 4 decimal places."""
        records = _make_temporal_records({
            "Player A": [
                ("2024-10-07 00:00:00", 1, 3),
                ("2024-10-14 00:00:00", 1, 1),  # stub
            ],
        })
        result = compute_cumulative_metrics(records)
        rate = result["cum_neg_rate"][0]
        assert rate == 0.3333

    def test_single_player_single_week(self):
        """Minimal input: one player, two weeks (one real + one stub)."""
        records = _make_temporal_records({
            "Solo": [
                ("2024-10-07 00:00:00", 4, 10),
                ("2024-10-14 00:00:00", 1, 5),  # stub
            ],
        })
        result = compute_cumulative_metrics(records)
        assert result.height == 1
        row = result.to_dicts()[0]
        assert row["attributed_player"] == "Solo"
        assert row["cum_neg"] == 4
        assert row["cum_total"] == 10
        assert row["cum_neg_rate"] == 0.4


class TestMaskBelowThreshold:
    """Tests for mask_below_threshold function."""

    def test_below_threshold_is_null(self):
        """Rows with cum_total below threshold get null cum_neg_rate."""
        records = _make_temporal_records({
            "Player A": [
                ("2024-10-07 00:00:00", 50, 500),
                ("2024-10-14 00:00:00", 60, 600),
                ("2024-10-21 00:00:00", 1, 10),  # stub
            ],
        })
        cumulative = compute_cumulative_metrics(records)
        # cum_total after week 1: 500, week 2: 1100
        masked = mask_below_threshold(cumulative, min_comments=1000)
        rows = masked.sort("week").to_dicts()

        assert rows[0]["cum_neg_rate"] is None  # 500 < 1000
        assert rows[1]["cum_neg_rate"] is not None  # 1100 >= 1000

    def test_above_threshold_preserved(self):
        """Rows at or above threshold retain their cum_neg_rate."""
        records = _make_temporal_records({
            "Player A": [
                ("2024-10-07 00:00:00", 100, 1000),
                ("2024-10-14 00:00:00", 1, 10),  # stub
            ],
        })
        cumulative = compute_cumulative_metrics(records)
        masked = mask_below_threshold(cumulative, min_comments=1000)
        row = masked.to_dicts()[0]
        assert row["cum_neg_rate"] == 0.1

    def test_custom_threshold(self):
        """Custom min_comments threshold is respected."""
        records = _make_temporal_records({
            "Player A": [
                ("2024-10-07 00:00:00", 25, 250),
                ("2024-10-14 00:00:00", 30, 300),
                ("2024-10-21 00:00:00", 1, 10),  # stub
            ],
        })
        cumulative = compute_cumulative_metrics(records)
        # cum_total: 250, 550
        masked = mask_below_threshold(cumulative, min_comments=500)
        rows = masked.sort("week").to_dicts()

        assert rows[0]["cum_neg_rate"] is None  # 250 < 500
        assert rows[1]["cum_neg_rate"] is not None  # 550 >= 500


class TestPivotBarRaceWide:
    """Tests for pivot_bar_race_wide function."""

    def _build_test_data(self):
        """Build test temporal records and metadata for pivot tests."""
        records = _make_temporal_records({
            "Player A": [
                ("2024-10-07 00:00:00", 100, 1000),
                ("2024-10-14 00:00:00", 150, 1500),
                ("2024-10-21 00:00:00", 1, 10),  # stub
            ],
            "Player B": [
                ("2024-10-07 00:00:00", 200, 1000),
                ("2024-10-14 00:00:00", 250, 1500),
                ("2024-10-21 00:00:00", 1, 10),  # stub
            ],
            "Player C": [
                ("2024-10-07 00:00:00", 50, 1000),
                ("2024-10-14 00:00:00", 80, 1500),
                ("2024-10-21 00:00:00", 1, 10),  # stub
            ],
        })
        metadata = {
            "Player A": {
                "team": "Team Alpha",
                "headshot_url": "https://cdn.example.com/a.png",
            },
            "Player B": {
                "team": "Team Beta",
                "headshot_url": "https://cdn.example.com/b.png",
            },
            "Player C": {
                "team": "Team Gamma",
                "headshot_url": "https://cdn.example.com/c.png",
            },
        }
        return records, metadata

    def test_output_columns_structure(self):
        """Output has Label, Category, Image, then date columns."""
        records, metadata = self._build_test_data()
        cumulative = compute_cumulative_metrics(records)
        wide = pivot_bar_race_wide(
            cumulative, metadata, top_n=3,
            min_ranking_comments=0, min_entry_comments=0,
        )

        cols = wide.columns
        assert cols[0] == "Label"
        assert cols[1] == "Category"
        assert cols[2] == "Image"
        assert len(cols) == 5  # 3 meta + 2 weeks

    def test_respects_top_n(self):
        """Only top_n players appear in output."""
        records, metadata = self._build_test_data()
        cumulative = compute_cumulative_metrics(records)
        wide = pivot_bar_race_wide(
            cumulative, metadata, top_n=2,
            min_ranking_comments=0, min_entry_comments=0,
        )

        assert wide.height == 2
        labels = wide["Label"].to_list()
        # Player B has highest final neg_rate, then Player A
        assert "Player B" in labels
        assert "Player A" in labels
        assert "Player C" not in labels

    def test_week_columns_are_iso_dates(self):
        """Week column headers match YYYY-MM-DD format."""
        import re

        records, metadata = self._build_test_data()
        cumulative = compute_cumulative_metrics(records)
        wide = pivot_bar_race_wide(
            cumulative, metadata, top_n=2,
            min_ranking_comments=0, min_entry_comments=0,
        )

        date_cols = [c for c in wide.columns if c not in {"Label", "Category", "Image"}]
        for col in date_cols:
            assert re.match(r"\d{4}-\d{2}-\d{2}", col), f"Bad date format: {col}"

    def test_masked_cells_are_null(self):
        """Cells masked below threshold appear as null in wide format."""
        records, metadata = self._build_test_data()
        cumulative = compute_cumulative_metrics(records)
        # Ranking threshold 0 lets all players qualify; entry threshold 1500
        # means week 1 (cum_total=1000) is below, week 2 (cum_total=2500) is above
        wide = pivot_bar_race_wide(
            cumulative, metadata, top_n=2,
            min_ranking_comments=0, min_entry_comments=1500,
        )

        # First week column should have null values
        first_week_col = wide.columns[3]
        vals = wide[first_week_col].to_list()
        assert all(v is None for v in vals)
