"""
Tests for sentiment aggregation logic.

Tests cover the pure functions resolve_player, extract_team_from_flair,
and compute_metrics from the aggregation pipeline.
"""

import logging
from datetime import date

import polars as pl
import pytest

from pipeline.aggregation import (
    aggregate_sentiment,
    build_teams_dimension,
    compute_cumulative_metrics,
    compute_metrics,
    extract_team_from_flair,
    mask_below_threshold,
    pivot_bar_race_wide,
    players_to_metadata_dict,
    resolve_player,
)
from pipeline.schemas import (
    AGGREGATE_VIEW_SCHEMAS,
    PLAYERS_SCHEMA,
    ROSTERS_SCHEMA,
    SCHEMA_VERSION,
    SENTIMENT_SCHEMA,
    TEAMS_SCHEMA,
)
from utils.player_config import load_player_config_version, load_player_metadata
from utils.season_config import get_active_season
from utils.team_config import load_team_config


class TestResolvePlayer:
    """Tests for resolve_player function."""

    def test_single_player_returns_it(self, player_alias_map):
        """Single player in mentioned_players is returned directly."""
        result = resolve_player(["LeBron James"], "Nikola Jokic", player_alias_map)
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

    def test_multi_player_punctuated_sentiment_player(self):
        """Multi-player sentiment_player with punctuation still attributes.

        Regression: the model emits "Michael Porter Jr." (trailing period) but
        the config alias is period-free. Without normalization the comment is
        dropped even though the player is already in mentioned_players.
        """
        alias_map = {
            "michael porter jr": "Michael Porter Jr",
            "lebron": "LeBron James",
        }
        result = resolve_player(
            ["Michael Porter Jr", "LeBron James"],
            "Michael Porter Jr.",
            alias_map,
        )
        assert result == "Michael Porter Jr"

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
        df = pl.DataFrame(
            {
                "player": ["A", "A", "A", "A", "A", "B", "B", "B"],
                "sentiment": ["neg", "neg", "pos", "neu", "neu", "neg", "pos", "pos"],
            }
        )

        result = compute_metrics(df, ["player"])

        # Player A: 2 neg, 1 pos, 2 neu = 5 total
        a = result.row(by_predicate=pl.col("player") == "A", named=True)
        assert a["neg_count"] == 2
        assert a["pos_count"] == 1
        assert a["neu_count"] == 2
        assert a["comment_count"] == 5
        assert a["neg_rate"] == 0.4
        assert a["pos_rate"] == 0.2
        assert a["net_sentiment"] == -0.2
        assert a["polarization"] == 0.6

        # Player B: 1 neg, 2 pos, 0 neu = 3 total
        b = result.row(by_predicate=pl.col("player") == "B", named=True)
        assert b["neg_count"] == 1
        assert b["pos_count"] == 2
        assert b["neu_count"] == 0
        assert b["comment_count"] == 3

    def test_rates_rounded_to_four_decimals(self):
        """Rate values are rounded to 4 decimal places."""
        df = pl.DataFrame(
            {
                "player": ["A", "A", "A"],
                "sentiment": ["neg", "pos", "pos"],
            }
        )

        result = compute_metrics(df, ["player"])
        a = result.row(0, named=True)

        assert a["neg_rate"] == 0.3333
        assert a["pos_rate"] == 0.6667

    def test_multi_group_columns(self):
        """Grouping by multiple columns works."""
        df = pl.DataFrame(
            {
                "player": ["A", "A", "B"],
                "team": ["LAL", "BOS", "LAL"],
                "sentiment": ["neg", "pos", "neu"],
            }
        )

        result = compute_metrics(df, ["player", "team"])
        assert result.height == 3

    def test_returns_frame_sorted_by_group_cols(self):
        """Output is a DataFrame deterministically sorted by the group columns."""
        df = pl.DataFrame(
            {
                "player": ["C", "A", "B"],
                "sentiment": ["neg", "pos", "neu"],
            }
        )

        result = compute_metrics(df, ["player"])

        assert isinstance(result, pl.DataFrame)
        assert result["player"].to_list() == ["A", "B", "C"]


def _make_test_parquet(tmp_path, rows, metadata=None):
    """Create a SENTIMENT_SCHEMA-conforming parquet for testing aggregate_sentiment.

    metadata, when given, is written as file-level key-value metadata
    (the config-lineage stamp from scripts/collect_results.py).
    """
    df = pl.DataFrame(rows, schema=SENTIMENT_SCHEMA)
    path = tmp_path / "test_sentiment.parquet"
    df.write_parquet(path, metadata=metadata)
    return path


def _lebron_rows() -> dict:
    """Two LeBron comments (Lakers + Celtics flair) in SENTIMENT_SCHEMA shape.

    Base rows for the Player-dimension tests; override columns to vary
    the mentioned players.
    """
    return {
        "comment_id": ["c1", "c2"],
        "body": ["LeBron is great", "LeBron is washed"],
        "author": ["u1", "u2"],
        "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
        "author_flair_css_class": ["lakers", "celtics"],
        "created_utc": [1704067200, 1704153600],
        "score": [10, 5],
        "link_id": ["t3_post123", "t3_post456"],
        "mentioned_players": [["LeBron James"], ["LeBron James"]],
        "sentiment": ["pos", "neg"],
        "confidence": [0.9, 0.8],
        "sentiment_player": ["LeBron James", "LeBron James"],
        "input_tokens": [100, 100],
        "output_tokens": [20, 20],
    }


def _lebron_parquet(tmp_path):
    """Parquet of _lebron_rows() — LeBron the only attributed player."""
    return _make_test_parquet(tmp_path, _lebron_rows())


def _write_snapshot(ref_dir, rows, season=None):
    """Overwrite the pinned snapshot with custom rows (season=None → active)."""
    pl.DataFrame(rows, schema=ROSTERS_SCHEMA).write_parquet(
        ref_dir / "rosters.parquet",
        metadata={"season": season or get_active_season()},
    )


@pytest.fixture(autouse=True)
def pinned_snapshot(monkeypatch, tmp_path, lebron_roster_row):
    """Pin pipeline.aggregation's reference dir to a tmp roster snapshot.

    Autouse so no test in this module reads the real data/ reference dir —
    aggregate_sentiment() takes the same code path on every machine.
    Defaults to a one-row LeBron snapshot stamped with the active season;
    tests needing other snapshot states overwrite or delete
    rosters.parquet in the returned dir.
    """
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("pipeline.aggregation.get_reference_dir", lambda: ref_dir)
    _write_snapshot(ref_dir, [lebron_roster_row])
    return ref_dir


class TestAggregatePlayers:
    """Tests for the players Player-dimension frame in aggregate output."""

    def test_players_is_frame_conforming_to_schema(self, tmp_path):
        """players is returned as a frame matching PLAYERS_SCHEMA; the legacy
        player_metadata key no longer appears in the return dict."""
        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        assert isinstance(result["players"], pl.DataFrame)
        assert result["players"].schema == PLAYERS_SCHEMA
        assert "player_metadata" not in result

    def test_config_side_populated(self, tmp_path):
        """Config columns carry the curated fields, roster team role-marked."""
        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        row = result["players"].row(
            by_predicate=pl.col("attributed_player") == "LeBron James", named=True
        )
        assert row["roster_team"] == "Los Angeles Lakers"
        assert row["conference"] == "West"
        assert row["player_id"] == 2544
        assert row["headshot_url"] is not None

    def test_snapshot_side_joined(self, tmp_path):
        """Snapshot columns join in via player_id."""
        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        row = result["players"].row(
            by_predicate=pl.col("attributed_player") == "LeBron James", named=True
        )
        assert row["position"] == "F"
        assert row["jersey_number"] == "23"
        assert row["height"] == "6-9"
        assert row["birth_date"] == date(1984, 12, 30)

    def test_excludes_non_attributed_players(self, tmp_path):
        """The frame only includes players that appear in player_overall."""
        result = aggregate_sentiment(_lebron_parquet(tmp_path))
        players = result["players"]["attributed_player"].to_list()

        assert players == ["LeBron James"]

    def test_multi_player_join_follows_config_order(
        self, tmp_path, pinned_snapshot, lebron_roster_row
    ):
        """Two attributed players: one row each, ordered by players.yaml."""
        giannis_row = {
            **lebron_roster_row,
            "player_id": 203507,
            "player_name": "Giannis Antetokounmpo",
            "team_name": "Milwaukee Bucks",
            "team_abbr": "MIL",
            "jersey_number": "34",
        }
        _write_snapshot(pinned_snapshot, [lebron_roster_row, giannis_row])
        path = _make_test_parquet(
            tmp_path,
            {
                **_lebron_rows(),
                "body": ["LeBron is great", "Giannis is a freak"],
                "mentioned_players": [["LeBron James"], ["Giannis Antetokounmpo"]],
                "sentiment_player": ["LeBron James", "Giannis Antetokounmpo"],
            },
        )

        result = aggregate_sentiment(path)

        expected_order = [
            player
            for player in load_player_metadata()
            if player in {"LeBron James", "Giannis Antetokounmpo"}
        ]
        assert result["players"]["attributed_player"].to_list() == expected_order
        row = result["players"].row(
            by_predicate=pl.col("attributed_player") == "Giannis Antetokounmpo",
            named=True,
        )
        assert row["jersey_number"] == "34"

    def test_duplicate_snapshot_player_id_raises(
        self, tmp_path, pinned_snapshot, lebron_roster_row
    ):
        """A duplicate player_id in the snapshot fails loudly, not by fanning
        the dimension out to multiple rows per player."""
        _write_snapshot(
            pinned_snapshot,
            [lebron_roster_row, {**lebron_roster_row, "team_abbr": "BOS"}],
        )

        with pytest.raises(ValueError, match="duplicate") as exc:
            aggregate_sentiment(_lebron_parquet(tmp_path))
        assert "2544" in str(exc.value)

    def test_missing_snapshot_row_nulls_and_logs(
        self, tmp_path, pinned_snapshot, lebron_roster_row, caplog
    ):
        """An attributed player absent from the snapshot gets null snapshot
        columns and is logged (the baked-config fallback case)."""
        _write_snapshot(
            pinned_snapshot,
            [{**lebron_roster_row, "player_id": 999, "player_name": "Other"}],
        )

        with caplog.at_level(logging.INFO, logger="pipeline.aggregation"):
            result = aggregate_sentiment(_lebron_parquet(tmp_path))

        row = result["players"].row(
            by_predicate=pl.col("attributed_player") == "LeBron James", named=True
        )
        assert row["roster_team"] == "Los Angeles Lakers"  # config side intact
        assert row["position"] is None
        assert row["birth_date"] is None
        assert "missing from the roster snapshot" in caplog.text
        assert "LeBron James" in caplog.text

    def test_missing_snapshot_file_warns_and_degrades(
        self, tmp_path, pinned_snapshot, caplog
    ):
        """No snapshot on disk: warn and ship the dimension with null
        snapshot columns (aggregation stays runnable without reference assets)."""
        (pinned_snapshot / "rosters.parquet").unlink()

        with caplog.at_level(logging.WARNING, logger="pipeline.aggregation"):
            result = aggregate_sentiment(_lebron_parquet(tmp_path))

        assert result["players"].schema == PLAYERS_SCHEMA
        row = result["players"].row(
            by_predicate=pl.col("attributed_player") == "LeBron James", named=True
        )
        assert row["roster_team"] == "Los Angeles Lakers"
        assert row["position"] is None
        assert "snapshot columns will be null" in caplog.text

    def test_snapshot_season_stamp_mismatch_warns(
        self, tmp_path, pinned_snapshot, lebron_roster_row, caplog
    ):
        """A snapshot stamped for another season triggers the lineage warning."""
        _write_snapshot(pinned_snapshot, [lebron_roster_row], season="1999-00")

        with caplog.at_level(logging.WARNING, logger="pipeline.aggregation"):
            aggregate_sentiment(_lebron_parquet(tmp_path))

        assert "season stamp" in caplog.text
        assert "1999-00" in caplog.text

    def test_unstamped_snapshot_warns_distinctly(
        self, tmp_path, pinned_snapshot, lebron_roster_row, caplog
    ):
        """A snapshot with no season stamp warns that lineage is unverifiable.

        Absent is not drift: the message must say lineage cannot be
        verified, not claim a season mismatch.
        """
        pl.DataFrame([lebron_roster_row], schema=ROSTERS_SCHEMA).write_parquet(
            pinned_snapshot / "rosters.parquet"
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.aggregation"):
            aggregate_sentiment(_lebron_parquet(tmp_path))

        assert "no season stamp" in caplog.text
        assert "does not match" not in caplog.text


class TestBuildTeamsDimension:
    """Tests for build_teams_dimension (pure config export)."""

    @pytest.fixture
    def two_team_config(self) -> dict[str, dict]:
        """Minimal two-team config in deliberate non-alphabetical order."""
        return {
            "Utah Jazz": {
                "abbreviation": "UTA",
                "conference": "West",
                "team_id": 1610612762,
                "logo_url": "https://cdn.nba.com/logos/nba/1610612762/primary/L/logo.svg",
                "aliases": ["uta", "jazz"],
            },
            "Boston Celtics": {
                "abbreviation": "BOS",
                "conference": "East",
                "team_id": 1610612738,
                "logo_url": "https://cdn.nba.com/logos/nba/1610612738/primary/L/logo.svg",
                "aliases": ["bos", "celtics"],
            },
        }

    def test_conforms_to_schema(self, two_team_config):
        """The frame matches TEAMS_SCHEMA exactly."""
        frame = build_teams_dimension(two_team_config)

        assert frame.schema == TEAMS_SCHEMA

    def test_preserves_config_order(self, two_team_config):
        """Rows follow teams.yaml insertion order, never sorted."""
        frame = build_teams_dimension(two_team_config)

        assert frame["team"].to_list() == ["Utah Jazz", "Boston Celtics"]

    def test_row_values_from_config(self, two_team_config):
        """Each descriptive column carries its config value."""
        frame = build_teams_dimension(two_team_config)

        row = frame.row(by_predicate=pl.col("team") == "Boston Celtics", named=True)
        assert row["abbreviation"] == "BOS"
        assert row["conference"] == "East"
        assert row["team_id"] == 1610612738
        assert row["logo_url"].endswith("1610612738/primary/L/logo.svg")

    def test_aliases_stay_config_only(self, two_team_config):
        """The dimension describes and slices; aliases never materialize."""
        frame = build_teams_dimension(two_team_config)

        assert "aliases" not in frame.columns


class TestAggregateTeams:
    """Tests for the teams Team-dimension frame in aggregate output."""

    def test_teams_is_frame_conforming_to_schema(self, tmp_path):
        """teams is returned as a frame matching TEAMS_SCHEMA."""
        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        assert isinstance(result["teams"], pl.DataFrame)
        assert result["teams"].schema == TEAMS_SCHEMA

    def test_all_30_franchises_in_config_order(self, tmp_path):
        """Every franchise ships, in teams.yaml order — the dimension is a
        pure config export, independent of which fan_teams the facts hit."""
        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        assert result["teams"]["team"].to_list() == list(load_team_config())
        assert result["teams"].height == 30


class TestPlayersToMetadataDict:
    """Tests for players_to_metadata_dict (frame -> legacy aggregates.json dict).

    These guard the consumer contract: aggregates.json must keep serving
    the nested {player: {...}} dict with the legacy value keys.
    """

    @pytest.fixture
    def players_frame(self) -> pl.DataFrame:
        """Two-row Player dimension frame conforming to PLAYERS_SCHEMA."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "roster_team": "Los Angeles Lakers",
                "conference": "West",
                "player_id": 2544,
                "headshot_url": "https://cdn.nba.com/headshots/nba/latest/1040x760/2544.png",
                "position": "F",
                "birth_date": date(1984, 12, 30),
                "experience": "21",
                "school": "St. Vincent-St. Mary HS (OH)",
                "jersey_number": "23",
                "height": "6-9",
                "weight": "250",
            },
            {
                "attributed_player": "Bam Adebayo",
                "roster_team": "Miami Heat",
                "conference": "East",
                "player_id": 1628389,
                "headshot_url": "https://cdn.nba.com/headshots/nba/latest/1040x760/1628389.png",
                "position": "C",
                "birth_date": date(1997, 7, 18),
                "experience": "8",
                "school": "Kentucky",
                "jersey_number": "13",
                "height": "6-9",
                "weight": "255",
            },
        ]
        return pl.DataFrame(rows, schema=PLAYERS_SCHEMA)

    def test_reconstructs_nested_dict_keyed_by_player(self, players_frame):
        """The dict keys by player name; roster_team serializes as legacy team."""
        as_dict = players_to_metadata_dict(players_frame)

        assert as_dict["LeBron James"]["team"] == "Los Angeles Lakers"
        assert as_dict["LeBron James"]["conference"] == "West"
        assert as_dict["Bam Adebayo"]["player_id"] == 1628389

    def test_value_keys_match_json_contract(self, players_frame):
        """Each entry carries exactly the legacy consumer keys, in order —
        no snapshot columns, no logo_url."""
        as_dict = players_to_metadata_dict(players_frame)

        assert list(as_dict["LeBron James"].keys()) == [
            "team",
            "conference",
            "player_id",
            "headshot_url",
        ]

    def test_preserves_row_order(self, players_frame):
        """Dict key order follows frame row order (players.yaml order)."""
        as_dict = players_to_metadata_dict(players_frame)

        assert list(as_dict.keys()) == players_frame["attributed_player"].to_list()


class TestConfigVersionLineage:
    """Tests for the players_config_version drift warning (#54)."""

    ROWS = {
        "comment_id": ["c1", "c2"],
        "body": ["LeBron is great", "LeBron is washed"],
        "author": ["u1", "u2"],
        "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
        "author_flair_css_class": ["lakers", "celtics"],
        "created_utc": [1704067200, 1704153600],
        "score": [10, 5],
        "link_id": ["t3_post123", "t3_post456"],
        "mentioned_players": [["LeBron James"], ["LeBron James"]],
        "sentiment": ["pos", "neg"],
        "confidence": [0.9, 0.8],
        "sentiment_player": ["LeBron James", "LeBron James"],
        "input_tokens": [100, 100],
        "output_tokens": [20, 20],
    }

    def _lineage_warnings(self, caplog) -> list[str]:
        """Extract WARNING messages about the config-version stamp."""
        return [
            record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
            and "players_config_version" in record.message
        ]

    def test_matching_stamp_emits_no_lineage_warning(self, tmp_path, caplog):
        """A stamp matching the on-disk config version stays silent."""
        # Arrange
        path = _make_test_parquet(
            tmp_path,
            self.ROWS,
            metadata={"players_config_version": load_player_config_version()},
        )

        # Act
        with caplog.at_level(logging.WARNING, logger="pipeline.aggregation"):
            aggregate_sentiment(path)

        # Assert
        assert self._lineage_warnings(caplog) == []

    def test_stamp_drift_warns_naming_both_versions(self, tmp_path, caplog):
        """A stamp differing from the on-disk config warns, naming both."""
        # Arrange
        path = _make_test_parquet(
            tmp_path, self.ROWS, metadata={"players_config_version": "0.1"}
        )

        # Act
        with caplog.at_level(logging.WARNING, logger="pipeline.aggregation"):
            aggregate_sentiment(path)

        # Assert
        warnings = self._lineage_warnings(caplog)
        assert len(warnings) == 1
        assert "0.1" in warnings[0]
        assert load_player_config_version() in warnings[0]

    def test_absent_stamp_warns_distinctly(self, tmp_path, caplog):
        """An unstamped parquet (pre-#54 legacy) warns with its own message.

        Absent is not drift: the message must say lineage cannot be
        verified, not claim a version mismatch.
        """
        # Arrange
        path = _make_test_parquet(tmp_path, self.ROWS)

        # Act
        with caplog.at_level(logging.WARNING, logger="pipeline.aggregation"):
            aggregate_sentiment(path)

        # Assert
        warnings = self._lineage_warnings(caplog)
        assert len(warnings) == 1
        assert "no players_config_version" in warnings[0]
        assert "drift" not in warnings[0]


class TestAggregateTeamConference:
    """Tests for conference field in team_overall rows."""

    def test_team_overall_has_conference(self, tmp_path):
        """Each team_overall row has a conference field."""
        path = _make_test_parquet(
            tmp_path,
            {
                "comment_id": ["c1", "c2"],
                "body": ["Go team", "Nice game"],
                "author": ["u1", "u2"],
                "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
                "author_flair_css_class": ["lakers", "celtics"],
                "created_utc": [1704067200, 1704153600],
                "score": [10, 5],
                "link_id": ["t3_post123", "t3_post456"],
                "mentioned_players": [[], []],
                "sentiment": ["pos", "neu"],
                "confidence": [0.9, 0.7],
                "sentiment_player": [None, None],
                "input_tokens": [100, 100],
                "output_tokens": [20, 20],
            },
        )

        result = aggregate_sentiment(path)

        for row in result["team_overall"].to_dicts():
            assert "conference" in row, f"Missing conference for {row['team']}"

    def test_conference_values_correct(self, tmp_path):
        """Conference values match expected East/West assignments."""
        path = _make_test_parquet(
            tmp_path,
            {
                "comment_id": ["c1", "c2"],
                "body": ["Go team", "Nice game"],
                "author": ["u1", "u2"],
                "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
                "author_flair_css_class": ["lakers", "celtics"],
                "created_utc": [1704067200, 1704153600],
                "score": [10, 5],
                "link_id": ["t3_post123", "t3_post456"],
                "mentioned_players": [[], []],
                "sentiment": ["pos", "neu"],
                "confidence": [0.9, 0.7],
                "sentiment_player": [None, None],
                "input_tokens": [100, 100],
                "output_tokens": [20, 20],
            },
        )

        result = aggregate_sentiment(path)
        team_by_name = {r["team"]: r for r in result["team_overall"].to_dicts()}

        assert team_by_name["Los Angeles Lakers"]["conference"] == "West"
        assert team_by_name["Boston Celtics"]["conference"] == "East"

    def test_team_overall_has_abbreviation(self, tmp_path):
        """Each team_overall row has the correct abbreviation."""
        path = _make_test_parquet(
            tmp_path,
            {
                "comment_id": ["c1", "c2"],
                "body": ["Go team", "Nice game"],
                "author": ["u1", "u2"],
                "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
                "author_flair_css_class": ["lakers", "celtics"],
                "created_utc": [1704067200, 1704153600],
                "score": [10, 5],
                "link_id": ["t3_post123", "t3_post456"],
                "mentioned_players": [[], []],
                "sentiment": ["pos", "neu"],
                "confidence": [0.9, 0.7],
                "sentiment_player": [None, None],
                "input_tokens": [100, 100],
                "output_tokens": [20, 20],
            },
        )

        result = aggregate_sentiment(path)
        team_by_name = {r["team"]: r for r in result["team_overall"].to_dicts()}

        assert team_by_name["Los Angeles Lakers"]["abbreviation"] == "LAL"
        assert team_by_name["Boston Celtics"]["abbreviation"] == "BOS"

    def test_team_overall_has_logo_url(self, tmp_path):
        """Each team_overall row has a logo_url field."""
        path = _make_test_parquet(
            tmp_path,
            {
                "comment_id": ["c1", "c2"],
                "body": ["Go team", "Nice game"],
                "author": ["u1", "u2"],
                "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
                "author_flair_css_class": ["lakers", "celtics"],
                "created_utc": [1704067200, 1704153600],
                "score": [10, 5],
                "link_id": ["t3_post123", "t3_post456"],
                "mentioned_players": [[], []],
                "sentiment": ["pos", "neu"],
                "confidence": [0.9, 0.7],
                "sentiment_player": [None, None],
                "input_tokens": [100, 100],
                "output_tokens": [20, 20],
            },
        )

        result = aggregate_sentiment(path)

        for row in result["team_overall"].to_dicts():
            assert "logo_url" in row, f"Missing logo_url for {row['team']}"
            assert row["logo_url"] is not None
            assert "cdn.nba.com/logos" in row["logo_url"]


class TestAggregateViews:
    """Tests for the four DataFrame views returned by aggregate_sentiment."""

    @pytest.fixture
    def views_parquet(self, tmp_path):
        """Parquet with attributed players and team flairs so all views are non-empty.

        neg_rates by player: Giannis 1.0, Kevin Durant 0.5, LeBron James 0.5
        (tie with Durant), Stephen Curry 0.0 — exercises the player_overall
        sort and its tiebreaker.
        """
        return _make_test_parquet(
            tmp_path,
            {
                "comment_id": ["c1", "c2", "c3", "c4", "c5", "c6"],
                "body": [
                    "Giannis traveled again",
                    "KD is a snake",
                    "KD is unstoppable",
                    "LeBron is washed",
                    "LeBron is the GOAT",
                    "Curry never misses",
                ],
                "author": ["u1", "u2", "u3", "u4", "u5", "u6"],
                "author_flair_text": [
                    ":lal-1: Lakers",
                    ":bos-1: Celtics",
                    ":lal-1: Lakers",
                    ":bos-1: Celtics",
                    ":lal-1: Lakers",
                    ":bos-1: Celtics",
                ],
                "author_flair_css_class": [
                    "lakers",
                    "celtics",
                    "lakers",
                    "celtics",
                    "lakers",
                    "celtics",
                ],
                "created_utc": [
                    1704067200,
                    1704067200,
                    1704067200,  # week of 2024-01-01
                    1704672000,
                    1704672000,
                    1704672000,  # week of 2024-01-08
                ],
                "score": [10, 5, 8, 3, 12, 7],
                "link_id": [
                    "t3_game1",
                    "t3_game1",
                    "t3_game1",
                    "t3_game2",
                    "t3_game2",
                    "t3_game2",
                ],
                "mentioned_players": [
                    ["Giannis Antetokounmpo"],
                    ["Kevin Durant"],
                    ["Kevin Durant"],
                    ["LeBron James"],
                    ["LeBron James"],
                    ["Stephen Curry"],
                ],
                "sentiment": ["neg", "neg", "pos", "neg", "pos", "pos"],
                "confidence": [0.9, 0.8, 0.9, 0.85, 0.95, 0.9],
                "sentiment_player": [
                    "Giannis Antetokounmpo",
                    "Kevin Durant",
                    "Kevin Durant",
                    "LeBron James",
                    "LeBron James",
                    "Stephen Curry",
                ],
                "input_tokens": [100, 100, 100, 100, 100, 100],
                "output_tokens": [20, 20, 20, 20, 20, 20],
            },
        )

    @pytest.mark.parametrize(
        "view_name,schema",
        AGGREGATE_VIEW_SCHEMAS.items(),
        ids=AGGREGATE_VIEW_SCHEMAS.keys(),
    )
    def test_views_conform_to_schemas(self, views_parquet, view_name, schema):
        """Each returned view matches its schema contract exactly."""
        result = aggregate_sentiment(views_parquet)

        assert result[view_name].schema == schema

    def test_player_overall_sorted_by_neg_rate_desc_then_player_asc(
        self, views_parquet
    ):
        """player_overall sorts by neg_rate descending, player name on ties."""
        result = aggregate_sentiment(views_parquet)

        players = result["player_overall"]["attributed_player"].to_list()
        assert players == [
            "Giannis Antetokounmpo",  # 1.0
            "Kevin Durant",  # 0.5 — tie, alphabetical before LeBron
            "LeBron James",  # 0.5
            "Stephen Curry",  # 0.0
        ]

    def test_rejects_nonconforming_input_parquet(self, tmp_path):
        """Input parquet not matching SENTIMENT_SCHEMA fails fast."""
        path = tmp_path / "bad.parquet"
        pl.DataFrame({"comment_id": ["c1"], "body": ["hello"]}).write_parquet(path)

        with pytest.raises(ValueError, match="Schema validation failed"):
            aggregate_sentiment(path)


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
            records.append(
                {
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
                }
            )
    return records


class TestComputeCumulativeMetrics:
    """Tests for compute_cumulative_metrics function."""

    def test_excludes_stub_week(self):
        """The maximum week (stub) is excluded from the output."""
        records = _make_temporal_records(
            {
                "Player A": [
                    ("2024-10-07 00:00:00", 5, 50),
                    ("2024-10-14 00:00:00", 10, 100),
                    ("2024-10-21 00:00:00", 2, 10),  # stub (max week)
                ],
            }
        )
        result = compute_cumulative_metrics(records)
        weeks = result["week"].to_list()
        from datetime import date

        assert date(2024, 10, 21) not in weeks
        assert len(weeks) == 2

    def test_cumulative_sums_correct(self):
        """Running neg and total counts accumulate across weeks."""
        records = _make_temporal_records(
            {
                "Player A": [
                    ("2024-10-07 00:00:00", 5, 50),
                    ("2024-10-14 00:00:00", 10, 100),
                    ("2024-10-21 00:00:00", 1, 10),  # stub
                ],
            }
        )
        result = compute_cumulative_metrics(records)
        rows = result.sort("week").to_dicts()

        assert rows[0]["cum_neg"] == 5
        assert rows[0]["cum_total"] == 50
        assert rows[1]["cum_neg"] == 15
        assert rows[1]["cum_total"] == 150

    def test_fills_missing_weeks(self):
        """A player missing from a week gets zero new counts, cumulative carries forward."""
        records = _make_temporal_records(
            {
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
            }
        )
        result = compute_cumulative_metrics(records)
        a_rows = (
            result.filter(pl.col("attributed_player") == "Player A")
            .sort("week")
            .to_dicts()
        )

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
        records = _make_temporal_records(
            {
                "Player A": [
                    ("2024-10-07 00:00:00", 1, 3),
                    ("2024-10-14 00:00:00", 1, 1),  # stub
                ],
            }
        )
        result = compute_cumulative_metrics(records)
        rate = result["cum_neg_rate"][0]
        assert rate == 0.3333

    def test_single_player_single_week(self):
        """Minimal input: one player, two weeks (one real + one stub)."""
        records = _make_temporal_records(
            {
                "Solo": [
                    ("2024-10-07 00:00:00", 4, 10),
                    ("2024-10-14 00:00:00", 1, 5),  # stub
                ],
            }
        )
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
        records = _make_temporal_records(
            {
                "Player A": [
                    ("2024-10-07 00:00:00", 50, 500),
                    ("2024-10-14 00:00:00", 60, 600),
                    ("2024-10-21 00:00:00", 1, 10),  # stub
                ],
            }
        )
        cumulative = compute_cumulative_metrics(records)
        # cum_total after week 1: 500, week 2: 1100
        masked = mask_below_threshold(cumulative, min_comments=1000)
        rows = masked.sort("week").to_dicts()

        assert rows[0]["cum_neg_rate"] is None  # 500 < 1000
        assert rows[1]["cum_neg_rate"] is not None  # 1100 >= 1000

    def test_above_threshold_preserved(self):
        """Rows at or above threshold retain their cum_neg_rate."""
        records = _make_temporal_records(
            {
                "Player A": [
                    ("2024-10-07 00:00:00", 100, 1000),
                    ("2024-10-14 00:00:00", 1, 10),  # stub
                ],
            }
        )
        cumulative = compute_cumulative_metrics(records)
        masked = mask_below_threshold(cumulative, min_comments=1000)
        row = masked.to_dicts()[0]
        assert row["cum_neg_rate"] == 0.1

    def test_custom_threshold(self):
        """Custom min_comments threshold is respected."""
        records = _make_temporal_records(
            {
                "Player A": [
                    ("2024-10-07 00:00:00", 25, 250),
                    ("2024-10-14 00:00:00", 30, 300),
                    ("2024-10-21 00:00:00", 1, 10),  # stub
                ],
            }
        )
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
        records = _make_temporal_records(
            {
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
            }
        )
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
            cumulative,
            metadata,
            top_n=3,
            min_ranking_comments=0,
            min_entry_comments=0,
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
            cumulative,
            metadata,
            top_n=2,
            min_ranking_comments=0,
            min_entry_comments=0,
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
            cumulative,
            metadata,
            top_n=2,
            min_ranking_comments=0,
            min_entry_comments=0,
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
            cumulative,
            metadata,
            top_n=2,
            min_ranking_comments=0,
            min_entry_comments=1500,
        )

        # First week column should have null values
        first_week_col = wide.columns[3]
        vals = wide[first_week_col].to_list()
        assert all(v is None for v in vals)


class TestAggregateMetadata:
    """Tests for the metadata key in aggregate output."""

    def test_metadata_includes_schema_version(self, tmp_path):
        """metadata carries the SCHEMA_VERSION from pipeline/schemas.py."""
        path = _make_test_parquet(
            tmp_path,
            {
                "comment_id": ["c1", "c2"],
                "body": ["LeBron is great", "LeBron is washed"],
                "author": ["u1", "u2"],
                "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
                "author_flair_css_class": ["lakers", "celtics"],
                "created_utc": [1704067200, 1704153600],
                "score": [10, 5],
                "link_id": ["t3_post123", "t3_post456"],
                "mentioned_players": [["LeBron James"], ["LeBron James"]],
                "sentiment": ["pos", "neg"],
                "confidence": [0.9, 0.8],
                "sentiment_player": ["LeBron James", "LeBron James"],
                "input_tokens": [100, 100],
                "output_tokens": [20, 20],
            },
        )

        result = aggregate_sentiment(path)

        assert result["metadata"]["schema_version"] == SCHEMA_VERSION

    def test_metadata_season_honors_override(self, tmp_path, season_override):
        """metadata.season reflects a --season override (#51).

        Pins that aggregation stamps the season via the override-aware
        get_active_season(), so a future direct load_season_config()
        read can't silently mislabel a backfill.
        """
        season_override("2024-25")
        path = _make_test_parquet(
            tmp_path,
            {
                "comment_id": ["c1", "c2"],
                "body": ["LeBron is great", "LeBron is washed"],
                "author": ["u1", "u2"],
                "author_flair_text": [":lal-1: Lakers", ":bos-1: Celtics"],
                "author_flair_css_class": ["lakers", "celtics"],
                "created_utc": [1704067200, 1704153600],
                "score": [10, 5],
                "link_id": ["t3_post123", "t3_post456"],
                "mentioned_players": [["LeBron James"], ["LeBron James"]],
                "sentiment": ["pos", "neg"],
                "confidence": [0.9, 0.8],
                "sentiment_player": ["LeBron James", "LeBron James"],
                "input_tokens": [100, 100],
                "output_tokens": [20, 20],
            },
        )

        result = aggregate_sentiment(path)

        assert result["metadata"]["season"] == "2024-25"
