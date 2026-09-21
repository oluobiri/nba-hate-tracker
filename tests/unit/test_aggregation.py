"""
Tests for sentiment aggregation logic.

Tests cover compute_metrics, the dimension builders, the attributed
frame loader, and aggregate_sentiment end to end.
"""

import json
import logging
from datetime import date
from unittest.mock import patch

import polars as pl
import pytest

from pipeline.aggregation import (
    _build_players_dimension,
    load_attributed_frame,
    aggregate_sentiment,
    attach_player_id,
    build_manifest,
    build_teams_dimension,
    compute_cumulative_metrics,
    compute_game_sentiment,
    compute_metrics,
    mask_below_threshold,
    pivot_bar_race_wide,
)
from pipeline.corpus import CORPUS_DAILY_FILENAME
from pipeline.games import PLAYER_GAME_LOG_FILENAME, TEAM_GAME_LOG_FILENAME
from pipeline.posts import POSTS_BRIDGE_FILENAME
from pipeline.schemas import (
    AGGREGATE_VIEW_SCHEMAS,
    CORPUS_DAILY_SCHEMA,
    CORPUS_STAGES,
    DASHBOARD_OUTPUT_SCHEMAS,
    METRIC_FORMULAS,
    NULLABLE_COLUMNS,
    POPULATIONS,
    TABLE_POPULATIONS,
    Manifest,
    GAME_SENTIMENT_SCHEMA,
    GAMES_SCHEMA,
    PLAYER_GAME_LOG_SCHEMA,
    PLAYER_GAMES_SCHEMA,
    TEAM_GAME_LOG_SCHEMA,
    COMMENT_SAMPLES_SCHEMA,
    PLAYERS_SCHEMA,
    POSTS_SCHEMA,
    ROSTERS_SCHEMA,
    SCHEMA_VERSION,
    SENTIMENT_SCHEMA,
    SENTIMENT_TARGETS_SCHEMA,
    TEAMS_SCHEMA,
)
from utils.constants import (
    BELT_MIN_N,
    COMMENT_SAMPLES_MAX_BODY_CHARS,
    COMMENT_SAMPLES_MIN_CONFIDENCE,
    COMMENT_SAMPLES_TOP_N,
    FANBASE_MIN_N,
    GAME_MIN_N,
    QUALIFIED_THRESHOLD,
    TARGET_POOL_K,
    WEEK_MIN_N,
)
from utils.player_config import (
    build_alias_to_player_map,
    load_player_config_version,
    load_player_metadata,
    resolve_player,
)
from utils.season_config import (
    get_active_season,
    load_season_config,
    load_season_config_version,
)
from utils.team_config import (
    build_alias_to_team_map,
    extract_team_from_flair,
    load_team_config,
    load_team_config_version,
)


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


def _derive(rows: dict) -> dict:
    """Add attributed_player and fan_team the way assembly does, if absent.

    Tests describe a comment by its mentions and flair; the materialized
    columns follow from those under the active configs.
    """
    if "attributed_player" in rows and "fan_team" in rows:
        return rows
    alias_map = build_alias_to_player_map()
    team_map = build_alias_to_team_map()
    return {
        **rows,
        "attributed_player": [
            resolve_player(mentions, pick, alias_map)
            for mentions, pick in zip(
                rows["mentioned_players"], rows["sentiment_player"]
            )
        ],
        "fan_team": [
            extract_team_from_flair(flair, team_map)
            for flair in rows["author_flair_text"]
        ],
    }


def _make_test_parquet(tmp_path, rows, metadata=None):
    """Create a SENTIMENT_SCHEMA-conforming parquet for testing aggregate_sentiment.

    attributed_player and fan_team are derived from the rows when not
    given. metadata, when given, is written as file-level key-value
    metadata (the config-lineage stamps from scripts/collect_results.py).
    """
    df = pl.DataFrame(_derive(rows), schema=SENTIMENT_SCHEMA)
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


def _lebron_rows_with_error() -> dict:
    """_lebron_rows plus one error-sentiment row aggregation must exclude."""
    rows = _lebron_rows()
    extra = {
        **{k: v[0] for k, v in rows.items()},
        "comment_id": "err01",
        "sentiment": "error",
    }
    return {k: v + [extra[k]] for k, v in rows.items()}


class TestLoadAttributedFrame:
    """Tests for load_attributed_frame, the model's shared starting frame."""

    def test_adds_week_and_drops_error_rows(self, tmp_path):
        """Verify the frame carries attributed_player, fan_team, and week; errors are excluded."""
        path = _make_test_parquet(tmp_path, _lebron_rows_with_error())

        df, excluded = load_attributed_frame(path)

        assert excluded == 1
        assert df.height == 2
        assert {"attributed_player", "fan_team", "week"} <= set(df.columns)
        assert "error" not in df["sentiment"].to_list()
        assert df["attributed_player"].to_list() == ["LeBron James"] * df.height

    def test_reads_materialized_columns_without_recomputing(self, tmp_path):
        """The stored attribution is read as-is, even where recomputation would differ.

        attributed_player and fan_team are assembly's derivations under
        the stamped configs; the reader trusts the file and the stamp
        check, so a stale file is read faithfully (and warned about),
        never silently re-resolved.
        """
        rows = {
            **_lebron_rows(),
            "attributed_player": ["Stored Player", None],
            "fan_team": [None, "Stored Team"],
        }
        path = _make_test_parquet(tmp_path, rows)

        df, _ = load_attributed_frame(path)

        assert df["attributed_player"].to_list() == ["Stored Player", None]
        assert df["fan_team"].to_list() == [None, "Stored Team"]

    def test_aggregate_sentiment_counts_match_the_frame(self, tmp_path):
        """Verify aggregate_sentiment's metadata counts derive from the same frame."""
        path = _make_test_parquet(tmp_path, _lebron_rows_with_error())

        df, excluded = load_attributed_frame(path)
        meta = aggregate_sentiment(path)["metadata"]

        assert meta["excluded_comments"] == excluded
        assert meta["usable_comments"] == df.height
        assert meta["total_comments"] == df.height + excluded


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

    def test_slug_derived_from_the_name(self, tmp_path):
        """The URL slug is built from attributed_player at aggregation."""
        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        row = result["players"].row(
            by_predicate=pl.col("attributed_player") == "LeBron James", named=True
        )
        assert row["slug"] == "lebron-james"

    def test_slug_collision_raises(self):
        """Two names folding to one slug fail the build, naming both."""
        metadata = {
            "P.J. Washington": {"team": "Dallas Mavericks", "player_id": 1},
            "P J Washington": {"team": "Dallas Mavericks", "player_id": 2},
        }

        with pytest.raises(ValueError, match=r"slug collision.*p-j-washington"):
            _build_players_dimension(metadata, set(metadata))

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


class TestAttachPlayerId:
    """Tests for attach_player_id (the Player dimension's id onto the fact)."""

    @pytest.fixture
    def players(self) -> pl.DataFrame:
        """Two-row Player dimension slice: name -> id."""
        return pl.DataFrame(
            {
                "attributed_player": ["LeBron James", "Jayson Tatum"],
                "player_id": [2544, 1628369],
            }
        )

    def test_id_lands_after_the_display_key_in_row_order(self, players):
        """player_id is inserted right after attributed_player; row order
        and the other columns are untouched."""
        df = pl.DataFrame(
            {
                "comment_id": ["c1", "c2", "c3"],
                "attributed_player": ["Jayson Tatum", "LeBron James", "Jayson Tatum"],
                "sentiment": ["neg", "pos", "neu"],
            }
        )

        out = attach_player_id(df, players)

        assert out.columns == [
            "comment_id",
            "attributed_player",
            "player_id",
            "sentiment",
        ]
        assert out["comment_id"].to_list() == ["c1", "c2", "c3"]
        assert out["player_id"].to_list() == [1628369, 2544, 1628369]

    def test_unattributed_rows_keep_a_null_id(self, players):
        """A null attributed_player is not an error; its id is null."""
        df = pl.DataFrame({"attributed_player": [None, "LeBron James"]})

        out = attach_player_id(df, players)

        assert out["player_id"].to_list() == [None, 2544]

    def test_attributed_row_without_an_id_raises(self, players):
        """An attributed player the dimension doesn't carry fails the build,
        naming the player."""
        df = pl.DataFrame({"attributed_player": ["LeBron James", "Stored Player"]})

        with pytest.raises(ValueError, match=r"Stored Player.*players\.yaml"):
            attach_player_id(df, players)

    def test_aggregate_sentiment_fails_on_a_player_outside_the_config(self, tmp_path):
        """A stale parquet attributing a player the active config doesn't
        carry stops the build instead of silently dropping the player."""
        rows = {
            **_lebron_rows(),
            "attributed_player": ["Stored Player", None],
            "fan_team": [None, None],
        }
        path = _make_test_parquet(tmp_path, rows)

        with pytest.raises(ValueError, match="Stored Player"):
            aggregate_sentiment(path)


class TestConfigVersionLineage:
    """Tests for the players_config_version drift warning."""

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
        """An unstamped parquet (legacy) warns with its own message.

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


class TestTeamsConfigVersionLineage:
    """Tests for the teams_config_version drift warning on fan_team."""

    ROWS = TestConfigVersionLineage.ROWS

    def _lineage_warnings(self, caplog) -> list[str]:
        """Extract WARNING messages about the teams config stamp."""
        return [
            record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
            and "teams_config_version" in record.message
        ]

    def test_matching_stamp_emits_no_lineage_warning(self, tmp_path, caplog):
        """A stamp matching the on-disk teams.yaml version stays silent."""
        path = _make_test_parquet(
            tmp_path,
            self.ROWS,
            metadata={"teams_config_version": load_team_config_version()},
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.aggregation"):
            aggregate_sentiment(path)

        assert self._lineage_warnings(caplog) == []

    def test_stamp_drift_warns_naming_both_versions_and_fan_team(
        self, tmp_path, caplog
    ):
        """A drifted teams stamp warns, naming both versions and fan_team."""
        path = _make_test_parquet(
            tmp_path, self.ROWS, metadata={"teams_config_version": "0.1"}
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.aggregation"):
            aggregate_sentiment(path)

        warnings = self._lineage_warnings(caplog)
        assert len(warnings) == 1
        assert "0.1" in warnings[0]
        assert load_team_config_version() in warnings[0]
        assert "fan_team" in warnings[0]

    def test_absent_stamp_warns_distinctly(self, tmp_path, caplog):
        """A parquet without the teams stamp warns that fan_team lineage is unverified."""
        path = _make_test_parquet(tmp_path, self.ROWS)

        with caplog.at_level(logging.WARNING, logger="pipeline.aggregation"):
            aggregate_sentiment(path)

        warnings = self._lineage_warnings(caplog)
        assert len(warnings) == 1
        assert "no teams_config_version" in warnings[0]
        assert "drift" not in warnings[0]


class TestAggregateTeamConference:
    """Tests for conference field in fan_team_overall rows."""

    def test_fan_team_overall_has_conference(self, tmp_path):
        """Each fan_team_overall row has a conference field."""
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

        for row in result["fan_team_overall"].to_dicts():
            assert "conference" in row, f"Missing conference for {row['fan_team']}"

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
        team_by_name = {r["fan_team"]: r for r in result["fan_team_overall"].to_dicts()}

        assert team_by_name["Los Angeles Lakers"]["conference"] == "West"
        assert team_by_name["Boston Celtics"]["conference"] == "East"

    def test_fan_team_overall_has_abbreviation(self, tmp_path):
        """Each fan_team_overall row has the correct abbreviation."""
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
        team_by_name = {r["fan_team"]: r for r in result["fan_team_overall"].to_dicts()}

        assert team_by_name["Los Angeles Lakers"]["abbreviation"] == "LAL"
        assert team_by_name["Boston Celtics"]["abbreviation"] == "BOS"

    def test_fan_team_overall_has_logo_url(self, tmp_path):
        """Each fan_team_overall row has a logo_url field."""
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

        team_config = load_team_config()
        for row in result["fan_team_overall"].to_dicts():
            assert "logo_url" in row, f"Missing logo_url for {row['fan_team']}"
            assert row["logo_url"] == team_config[row["fan_team"]]["logo_url"]


class TestAggregateViews:
    """Tests for the four DataFrame views returned by aggregate_sentiment."""

    @pytest.fixture
    def views_parquet(self, tmp_path):
        """Parquet with attributed players and team flairs so all views are non-empty.

        neg_rates by player: Giannis 1.0, Kevin Durant 0.5, LeBron James 0.5
        (tie with Durant), Stephen Curry 0.0 — exercises the player_overall
        sort and its tiebreaker. c7 is a Giannis neg with no stated target
        (sentiment_player null): attributed by the single-mention rule
        (Giannis stays 1.0), gated out of the receipts despite the top score.
        """
        return _make_test_parquet(
            tmp_path,
            {
                "comment_id": ["c1", "c2", "c3", "c4", "c5", "c6", "c7"],
                "body": [
                    "Giannis traveled again",
                    "KD is a snake",
                    "KD is unstoppable",
                    "LeBron is washed",
                    "LeBron is the GOAT",
                    "Curry never misses",
                    "You were fouling Giannis all game",
                ],
                "author": ["u1", "u2", "u3", "u4", "u5", "u6", "u7"],
                "author_flair_text": [
                    ":lal-1: Lakers",
                    ":bos-1: Celtics",
                    ":lal-1: Lakers",
                    ":bos-1: Celtics",
                    ":lal-1: Lakers",
                    ":bos-1: Celtics",
                    ":bos-1: Celtics",
                ],
                "author_flair_css_class": [
                    "lakers",
                    "celtics",
                    "lakers",
                    "celtics",
                    "lakers",
                    "celtics",
                    "celtics",
                ],
                "created_utc": [
                    1704067200,
                    1704067200,
                    1704067200,  # week of 2024-01-01
                    1704672000,
                    1704672000,
                    1704672000,  # week of 2024-01-08
                    1704067200,  # week of 2024-01-01
                ],
                "score": [10, 5, 8, 3, 12, 7, 100],
                "link_id": [
                    "t3_game1",
                    "t3_game1",
                    "t3_game1",
                    "t3_game2",
                    "t3_game2",
                    "t3_game2",
                    "t3_game1",
                ],
                "mentioned_players": [
                    ["Giannis Antetokounmpo"],
                    ["Kevin Durant"],
                    ["Kevin Durant"],
                    ["LeBron James"],
                    ["LeBron James"],
                    ["Stephen Curry"],
                    ["Giannis Antetokounmpo"],
                ],
                "sentiment": ["neg", "neg", "pos", "neg", "pos", "pos", "neg"],
                "confidence": [0.9, 0.8, 0.9, 0.85, 0.95, 0.9, 0.95],
                "sentiment_player": [
                    "Giannis Antetokounmpo",
                    "Kevin Durant",
                    "Kevin Durant",
                    "LeBron James",
                    "LeBron James",
                    "Stephen Curry",
                    None,
                ],
                "input_tokens": [100, 100, 100, 100, 100, 100, 100],
                "output_tokens": [20, 20, 20, 20, 20, 20, 20],
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

    def test_comment_samples_conforms_to_schema(self, views_parquet):
        """comment_samples is returned as a frame matching its contract —
        a dedicated check, since the parametrized one above iterates the
        rollup registry only."""
        result = aggregate_sentiment(views_parquet)

        assert isinstance(result["comment_samples"], pl.DataFrame)
        assert result["comment_samples"].schema == COMMENT_SAMPLES_SCHEMA

    def test_comment_samples_selects_from_attributed_frame(self, views_parquet):
        """Samples come from the attributed, flair-resolved rows: LeBron's
        pos rank-1 is c5 with its Lakers fan_team; c4 (0.85) is gated out."""
        result = aggregate_sentiment(views_parquet)
        samples = result["comment_samples"]

        lebron = samples.filter(pl.col("attributed_player") == "LeBron James")
        assert lebron.select("sentiment", "rank", "comment_id").rows() == [
            ("pos", 1, "c5"),
        ]
        assert lebron["body"][0] == "LeBron is the GOAT"
        assert lebron["fan_team"][0] == "Los Angeles Lakers"
        assert "c4" not in samples["comment_id"].to_list()

    def test_target_gate_diverges_from_attribution(self, views_parquet):
        """Both sides of the receipts/aggregate divergence: c7 (polar,
        null sentiment_player) is counted in player_overall — attribution
        is untouched by the gate — yet never appears in comment_samples,
        where c1, the named-target Giannis neg it out-scores, keeps
        rank 1."""
        result = aggregate_sentiment(views_parquet)

        giannis = result["player_overall"].filter(
            pl.col("attributed_player") == "Giannis Antetokounmpo"
        )
        assert giannis["comment_count"][0] == 2
        assert giannis["neg_count"][0] == 2
        sampled_ids = result["comment_samples"]["comment_id"].to_list()
        assert "c7" not in sampled_ids
        assert "c1" in sampled_ids

    def test_verdict_sidecar_replaces_the_gate(self, views_parquet, tmp_path):
        """Under a sidecar the verifier decides: c7 (unnamed, affirmed) is
        re-admitted at rank 1 over c1 (named, screened as a null target),
        and the metadata reports the verified posture with its figures."""
        sidecar = tmp_path / "sentiment_targets.parquet"
        pl.DataFrame(
            {
                "comment_id": ["c7", "c1", "c5"],
                "attributed_player": ["Giannis Antetokounmpo"] * 2 + ["LeBron James"],
                "sentiment": ["neg", "neg", "pos"],
                "stratum": ["candidate"] * 3,
                "rank": [1, 2, 1],
                "target_raw": ["Giannis", None, "LeBron"],
                "target_confidence": [0.9, 0.9, 0.9],
                "valid": [True, True, True],
                "input_tokens": [100] * 3,
                "output_tokens": [10] * 3,
            },
            schema=SENTIMENT_TARGETS_SCHEMA,
        ).write_parquet(
            sidecar,
            metadata={
                "classifier_target_model": "claude-sonnet-5",
                "classifier_target_prompt_version": "v1",
                "players_config_version": load_player_config_version(),
            },
        )

        result = aggregate_sentiment(views_parquet, sidecar)

        giannis = result["comment_samples"].filter(
            pl.col("attributed_player") == "Giannis Antetokounmpo"
        )
        assert giannis.select("sentiment", "rank", "comment_id").rows() == [
            ("neg", 1, "c7"),
        ]
        meta = result["metadata"]
        assert meta["receipts_verified"] is True
        assert meta["classifier_target_model"] == "claude-sonnet-5"
        assert meta["classifier_target_prompt_version"] == "v1"
        assert 0.0 < meta["receipts_coverage"] < 1.0  # c2, c3 uncovered
        assert meta["receipts_precision"] == 0.5  # c1 null, c5 affirmed

    def test_no_sidecar_reports_unverified(self, views_parquet):
        """Fallback posture: the flag is false and the figures are null."""
        result = aggregate_sentiment(views_parquet)

        meta = result["metadata"]
        assert meta["receipts_verified"] is False
        assert meta["receipts_coverage"] is None
        assert meta["receipts_precision"] is None
        assert meta["classifier_target_model"] is None

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
) -> pl.DataFrame:
    """Build a player_temporal-shaped frame for testing.

    Args:
        players_weeks: Mapping of player name to list of
            (week_str, neg_count, comment_count) tuples.

    Returns:
        Frame matching the player_temporal view, week as Datetime("us").
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
    return pl.DataFrame(records).with_columns(
        pl.col("week").str.to_datetime(time_unit="us")
    )


def _manifest_inputs() -> tuple[dict, dict, dict, dict]:
    """Minimal (outputs, metadata, season_config, config_versions) for
    build_manifest: empty frames except a two-row player_overall, a
    verified receipts block, both classifier stages stamped."""
    outputs = {
        name: pl.DataFrame(schema=schema)
        for name, schema in DASHBOARD_OUTPUT_SCHEMAS.items()
    }
    outputs["player_overall"] = pl.DataFrame(
        {
            "attributed_player": ["LeBron James", "Luka Doncic"],
            "player_id": [2544, 1629029],
            "neg_count": [1, 2],
            "pos_count": [1, 0],
            "neu_count": [0, 0],
            "comment_count": [2, 2],
            "neg_rate": [0.5, 1.0],
            "pos_rate": [0.5, 0.0],
            "net_sentiment": [0.0, -1.0],
            "polarization": [1.0, 1.0],
        },
        schema=DASHBOARD_OUTPUT_SCHEMAS["player_overall"],
    )
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "season": "2025-26",
        "generated_at": "2026-09-16T12:00:00+00:00",
        "total_comments": 7,
        "usable_comments": 6,
        "excluded_comments": 1,
        "attributed_comments": 4,
        "classifier_sentiment_model": "claude-haiku-4-5-20251001",
        "classifier_sentiment_prompt_version": "v2-production+s-hint",
        "classifier_target_model": "claude-sonnet-5",
        "classifier_target_prompt_version": "v1",
        "games_fetched_at": "2026-09-12",
        "posts_processed_at": "2026-09-13",
        "corpus_daily_processed_at": "2026-09-16",
        "receipts_verified": True,
        "receipts_coverage": 0.999,
        "receipts_precision": 0.777,
        "attribution_toward_share": 0.74,
    }
    season_config = {
        "calendar": {"opening_night": "2025-10-21", "finals_end": None},
        "corpus": {"raw_comments": 100, "population_submitted": 50},
    }
    config_versions = {"players": "4.5", "teams": "2.2", "season": "2.0"}
    return outputs, metadata, season_config, config_versions


class TestBuildManifest:
    """Tests for build_manifest, the pure projection of a build onto the contract."""

    def test_keys_follow_the_contract_in_block_order(self):
        """The manifest's top-level keys are exactly the Manifest fields, in order."""
        manifest = build_manifest(*_manifest_inputs())

        assert list(manifest) == list(Manifest.__annotations__)

    def test_is_json_serializable(self):
        """Read-only config mappings become plain dicts; the file is plain JSON."""
        manifest = build_manifest(*_manifest_inputs())

        assert json.loads(json.dumps(manifest)) == manifest

    def test_identity_block(self):
        """schema_version, season and generated_at come from the build;
        config_versions is every registered config's version."""
        manifest = build_manifest(*_manifest_inputs())

        assert manifest["schema_version"] == SCHEMA_VERSION
        assert manifest["season"] == "2025-26"
        assert manifest["generated_at"] == "2026-09-16T12:00:00+00:00"
        assert manifest["config_versions"] == {
            "players": "4.5",
            "teams": "2.2",
            "season": "2.0",
        }
        assert manifest["snapshots"] == {
            "games_fetched_at": "2026-09-12",
            "posts_processed_at": "2026-09-13",
            "corpus_daily_processed_at": "2026-09-16",
        }

    def test_classifiers_by_stage_from_the_stamps(self):
        """Each stamped stage is a {model, prompt_version} block."""
        manifest = build_manifest(*_manifest_inputs())

        assert manifest["classifiers"] == {
            "sentiment": {
                "model": "claude-haiku-4-5-20251001",
                "prompt_version": "v2-production+s-hint",
            },
            "target": {"model": "claude-sonnet-5", "prompt_version": "v1"},
        }

    def test_unstamped_stage_is_absent(self):
        """Feature detection: a stage with no stamps has no block, not nulls."""
        outputs, metadata, season_config, versions = _manifest_inputs()
        metadata["classifier_target_model"] = None
        metadata["classifier_target_prompt_version"] = None

        manifest = build_manifest(outputs, metadata, season_config, versions)

        assert list(manifest["classifiers"]) == ["sentiment"]

    def test_half_stamped_stage_is_absent(self):
        """A stage needs both stamps to be an identity; one alone is no block."""
        outputs, metadata, season_config, versions = _manifest_inputs()
        metadata["classifier_target_prompt_version"] = None

        manifest = build_manifest(outputs, metadata, season_config, versions)

        assert list(manifest["classifiers"]) == ["sentiment"]

    def test_rules_publish_the_constants(self):
        """The threshold, samples rule, floors and formulas are the named
        constants, never retyped."""
        rules = build_manifest(*_manifest_inputs())["rules"]

        assert rules["qualified_threshold"] == QUALIFIED_THRESHOLD
        assert rules["samples"] == {
            "top_n": COMMENT_SAMPLES_TOP_N,
            "min_confidence": COMMENT_SAMPLES_MIN_CONFIDENCE,
            "max_body_chars": COMMENT_SAMPLES_MAX_BODY_CHARS,
            "requires_target": False,
            "pool_k": TARGET_POOL_K,
            "admission": "verified",
        }
        assert rules["floors"] == {
            "fanbase_min_n": FANBASE_MIN_N,
            "week_min_n": WEEK_MIN_N,
            "belt_min_n": BELT_MIN_N,
            "game_min_n": GAME_MIN_N,
        }
        assert rules["metrics"] == METRIC_FORMULAS

    def test_receipts_figures_pass_through(self):
        """The verifier's figures ride under rules.receipts."""
        rules = build_manifest(*_manifest_inputs())["rules"]

        assert rules["receipts"] == {
            "verified": True,
            "coverage": 0.999,
            "precision": 0.777,
            "attribution_toward_share": 0.74,
        }

    def test_gate_only_fallback_says_so(self):
        """Without a sidecar the samples admit on the gate and the figures are null."""
        outputs, metadata, season_config, versions = _manifest_inputs()
        metadata.update(
            receipts_verified=False,
            receipts_coverage=None,
            receipts_precision=None,
            attribution_toward_share=None,
        )

        rules = build_manifest(outputs, metadata, season_config, versions)["rules"]

        assert rules["samples"]["admission"] == "gate_only"
        assert rules["samples"]["requires_target"] is True
        assert rules["receipts"] == {
            "verified": False,
            "coverage": None,
            "precision": None,
            "attribution_toward_share": None,
        }

    def test_calendar_is_the_season_facts(self):
        """The calendar block is season.yaml's, nulls kept, as a plain dict."""
        manifest = build_manifest(*_manifest_inputs())

        assert manifest["calendar"] == {
            "opening_night": "2025-10-21",
            "finals_end": None,
        }

    def test_corpus_funnel_relayed_then_derived(self):
        """The recorded stages come from season.yaml, the rest from the
        build, in CORPUS_STAGES order; classified is every fact row."""
        manifest = build_manifest(*_manifest_inputs())

        assert list(manifest["corpus"]) == list(CORPUS_STAGES)
        assert manifest["corpus"] == {
            "raw_comments": 100,
            "population_submitted": 50,
            "classified": 7,
            "usable": 6,
            "attributed": 4,
        }
        assert manifest["populations"] == POPULATIONS

    def test_tables_enumerate_every_output_with_rows_and_population(self):
        """The registry is generated from DASHBOARD_OUTPUT_SCHEMAS: file,
        row count and the population each table draws from."""
        manifest = build_manifest(*_manifest_inputs())

        assert list(manifest["tables"]) == list(DASHBOARD_OUTPUT_SCHEMAS)
        assert manifest["tables"]["player_overall"] == {
            "file": "player_overall.parquet",
            "rows": 2,
            "population": "attributed",
        }
        assert manifest["tables"]["players"] == {
            "file": "players.parquet",
            "rows": 0,
            "population": None,
        }
        for name, entry in manifest["tables"].items():
            assert entry["population"] == TABLE_POPULATIONS[name]

    def test_aggregate_sentiment_returns_the_manifest(self, tmp_path):
        """End to end: the fact's classifier stamps reach the manifest, the
        counts are the build's, and the table rows match the frames."""
        path = _make_test_parquet(
            tmp_path,
            _lebron_rows_with_error(),
            metadata={
                "classifier_sentiment_model": "claude-haiku-4-5-20251001",
                "classifier_sentiment_prompt_version": "v2-production+s-hint",
            },
        )

        result = aggregate_sentiment(path)
        manifest = result["manifest"]

        assert manifest["season"] == get_active_season()
        assert manifest["classifiers"] == {
            "sentiment": {
                "model": "claude-haiku-4-5-20251001",
                "prompt_version": "v2-production+s-hint",
            }
        }
        assert manifest["config_versions"] == {
            "players": load_player_config_version(),
            "teams": load_team_config_version(),
            "season": load_season_config_version(),
        }
        assert manifest["corpus"]["classified"] == 3
        assert manifest["corpus"]["usable"] == 2
        assert manifest["corpus"]["attributed"] == 2
        assert manifest["rules"]["receipts"]["verified"] is False
        for name in DASHBOARD_OUTPUT_SCHEMAS:
            assert manifest["tables"][name]["rows"] == result[name].height
        json.dumps(manifest)


class TestNullabilityEnforcement:
    """The write boundary checks every output against the nullable registry."""

    def test_every_output_is_checked_with_its_declared_set(self, tmp_path):
        """aggregate_sentiment validates nullability once per produced
        table, passing that table's declared nullable columns."""
        path = _lebron_parquet(tmp_path)

        with patch("pipeline.aggregation.validate_nullability") as check:
            aggregate_sentiment(path)

        checked = {call.args[2]: call.args[1] for call in check.call_args_list}
        assert checked == NULLABLE_COLUMNS
        assert check.call_count == len(DASHBOARD_OUTPUT_SCHEMAS)


class TestAggregateCorpusDaily:
    """Tests for the corpus snapshot's passage through aggregate_sentiment."""

    def test_no_snapshot_ships_empty_table(self, tmp_path, pinned_snapshot):
        """Without a snapshot the table is empty but present and conforming."""
        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        assert result["corpus_daily"].schema == CORPUS_DAILY_SCHEMA
        assert result["corpus_daily"].height == 0
        assert result["metadata"]["corpus_daily_processed_at"] is None
        assert result["manifest"]["snapshots"]["corpus_daily_processed_at"] is None
        assert result["manifest"]["tables"]["corpus_daily"]["rows"] == 0

    def test_snapshot_ships_when_its_totals_match_the_record(
        self, tmp_path, pinned_snapshot
    ):
        """A snapshot whose owned sums equal season.yaml's figures is
        exported as cached, its build date in the manifest."""
        corpus = load_season_config()["corpus"]
        pl.DataFrame(
            {
                "day": [date(2025, 10, 1)],
                "raw_comments": [corpus["raw_comments"]],
                "population_submitted": [corpus["population_submitted"]],
                "usable": [1],
                "attributed": [1],
            },
            schema=CORPUS_DAILY_SCHEMA,
        ).write_parquet(
            pinned_snapshot / CORPUS_DAILY_FILENAME,
            metadata={"season": get_active_season(), "processed_at": "2026-09-16"},
        )

        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        assert result["corpus_daily"].height == 1
        assert result["manifest"]["snapshots"]["corpus_daily_processed_at"] == (
            "2026-09-16"
        )
        assert result["manifest"]["tables"]["corpus_daily"] == {
            "file": "corpus_daily.parquet",
            "rows": 1,
            "population": None,
        }

    def test_mismatched_snapshot_aborts_the_build(self, tmp_path, pinned_snapshot):
        """A snapshot that disagrees with season.yaml fails aggregation
        outright, before anything could be written."""
        pl.DataFrame(
            {
                "day": [date(2025, 10, 1)],
                "raw_comments": [1],
                "population_submitted": [1],
                "usable": [1],
                "attributed": [1],
            },
            schema=CORPUS_DAILY_SCHEMA,
        ).write_parquet(
            pinned_snapshot / CORPUS_DAILY_FILENAME,
            metadata={"season": get_active_season(), "processed_at": "2026-09-16"},
        )

        with pytest.raises(ValueError, match="one owner"):
            aggregate_sentiment(_lebron_parquet(tmp_path))


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
        players = pl.DataFrame(
            {
                "attributed_player": ["Player A", "Player B", "Player C"],
                "roster_team": ["Team Alpha", "Team Beta", "Team Gamma"],
                "headshot_url": [
                    "https://cdn.example.com/a.png",
                    "https://cdn.example.com/b.png",
                    "https://cdn.example.com/c.png",
                ],
            }
        )
        return records, players

    def test_output_columns_structure(self):
        """Output has Label, Category, Image, then date columns."""
        records, players = self._build_test_data()
        cumulative = compute_cumulative_metrics(records)
        wide = pivot_bar_race_wide(
            cumulative,
            players,
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
        records, players = self._build_test_data()
        cumulative = compute_cumulative_metrics(records)
        wide = pivot_bar_race_wide(
            cumulative,
            players,
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

        records, players = self._build_test_data()
        cumulative = compute_cumulative_metrics(records)
        wide = pivot_bar_race_wide(
            cumulative,
            players,
            top_n=2,
            min_ranking_comments=0,
            min_entry_comments=0,
        )

        date_cols = [c for c in wide.columns if c not in {"Label", "Category", "Image"}]
        for col in date_cols:
            assert re.match(r"\d{4}-\d{2}-\d{2}", col), f"Bad date format: {col}"

    def test_masked_cells_are_null(self):
        """Cells masked below threshold appear as null in wide format."""
        records, players = self._build_test_data()
        cumulative = compute_cumulative_metrics(records)
        # Ranking threshold 0 lets all players qualify; entry threshold 1500
        # means week 1 (cum_total=1000) is below, week 2 (cum_total=2500) is above
        wide = pivot_bar_race_wide(
            cumulative,
            players,
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


class TestClassifierLineage:
    """Tests for the classifier identity stamp readback (#90)."""

    ROWS = TestConfigVersionLineage.ROWS

    def _classifier_warnings(self, caplog) -> list[str]:
        """Extract WARNING messages about the classifier identity stamp."""
        return [
            record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
            and "classifier identity" in record.message
        ]

    def test_stamped_parquet_emits_no_warning(self, tmp_path, caplog):
        """A parquet carrying both classifier keys stays silent."""
        # Arrange
        path = _make_test_parquet(
            tmp_path,
            self.ROWS,
            metadata={
                "players_config_version": load_player_config_version(),
                "classifier_sentiment_model": "claude-haiku-4-5-20251001",
                "classifier_sentiment_prompt_version": "v2-production+s-hint",
            },
        )

        # Act
        with caplog.at_level(logging.WARNING, logger="pipeline.aggregation"):
            aggregate_sentiment(path)

        # Assert
        assert self._classifier_warnings(caplog) == []

    def test_absent_stamp_warns(self, tmp_path, caplog):
        """A parquet with no classifier identity warns once.

        A birth certificate has nothing live to drift against, so
        absence is the only warnable condition — no drift variant.
        """
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
        warnings = self._classifier_warnings(caplog)
        assert len(warnings) == 1
        assert "no classifier identity" in warnings[0]


_BOX = {
    "minutes": 34,
    "fgm": 10,
    "fga": 20,
    "fg3m": 2,
    "fg3a": 6,
    "ftm": 6,
    "fta": 8,
    "oreb": 1,
    "dreb": 7,
    "reb": 8,
    "ast": 9,
    "stl": 1,
    "blk": 1,
    "tov": 3,
    "pf": 2,
    "pts": 28,
    "plus_minus": 6,
}


def _write_game_logs(ref_dir, season=None):
    """One Lakers home win over Boston with a LeBron line."""
    common = {
        "season_type": "Regular Season",
        "game_id": "0022500001",
        "game_date": date(2025, 10, 21),
    }
    team_rows = [
        {
            **common,
            "team_id": 1610612747,
            "team_abbr": "LAL",
            "team_name": "Los Angeles Lakers",
            "matchup": "LAL vs. BOS",
            "wl": "W",
            **{**_BOX, "pts": 110},
        },
        {
            **common,
            "team_id": 1610612738,
            "team_abbr": "BOS",
            "team_name": "Boston Celtics",
            "matchup": "BOS @ LAL",
            "wl": "L",
            **{**_BOX, "pts": 100},
        },
    ]
    player_rows = [
        {
            **common,
            "player_id": 2544,
            "player_name": "LeBron James",
            "team_id": 1610612747,
            "team_abbr": "LAL",
            "matchup": "LAL vs. BOS",
            "wl": "W",
            **_BOX,
        }
    ]
    pl.DataFrame(team_rows, schema=TEAM_GAME_LOG_SCHEMA).write_parquet(
        ref_dir / TEAM_GAME_LOG_FILENAME,
        metadata={
            "season": season or get_active_season(),
            "fetched_at": "2026-09-12",
        },
    )
    pl.DataFrame(player_rows, schema=PLAYER_GAME_LOG_SCHEMA).write_parquet(
        ref_dir / PLAYER_GAME_LOG_FILENAME
    )


class TestAggregateGames:
    """Tests for the game layer's passage through aggregate_sentiment."""

    def test_no_snapshots_ships_empty_tables(self, tmp_path, pinned_snapshot):
        """Without game logs the tables are empty but present and conforming."""
        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        assert result["games"].schema == GAMES_SCHEMA
        assert result["player_games"].schema == PLAYER_GAMES_SCHEMA
        assert result["games"].height == 0
        assert result["metadata"]["game_count"] == 0
        assert result["metadata"]["games_fetched_at"] is None

    def test_builds_tables_from_snapshots(self, tmp_path, pinned_snapshot):
        """Game logs on disk become games + LeBron's line, under the real configs."""
        _write_game_logs(pinned_snapshot)

        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        game = result["games"].row(0, named=True)
        assert game["home_team"] == "Los Angeles Lakers"
        assert game["winner"] == "Los Angeles Lakers"
        line = result["player_games"].row(0, named=True)
        assert line["attributed_player"] == "LeBron James"
        assert line["roster_team"] == "Los Angeles Lakers"
        assert line["opponent"] == "Boston Celtics"
        assert line["is_home"] is True
        assert result["metadata"]["game_count"] == 1
        assert result["metadata"]["player_game_count"] == 1
        assert result["metadata"]["games_fetched_at"] == "2026-09-12"


def _write_posts_bridge(ref_dir, rows, season=None):
    """A bridge derived from the same fetch as _write_game_logs."""
    pl.DataFrame(rows, schema=POSTS_SCHEMA).write_parquet(
        ref_dir / POSTS_BRIDGE_FILENAME,
        metadata={
            "season": season or get_active_season(),
            "processed_at": "2026-09-13",
            "games_fetched_at": "2026-09-12",
        },
    )


def _post_row(post_id, post_type, game_id, is_primary):
    """One POSTS_SCHEMA row; the bridge's derived trio, the rest fixed."""
    return {
        "post_id": post_id,
        "title": f"title {post_id}",
        "created_utc": 1704067200,
        "score": 1,
        "num_comments": 10,
        "link_flair_text": None,
        "post_type": post_type,
        "game_id": game_id,
        "is_primary": is_primary,
    }


class TestAggregatePosts:
    """Tests for the Post bridge's passage through aggregate_sentiment."""

    def _row(self, post_id, post_type, game_id, is_primary):
        return _post_row(post_id, post_type, game_id, is_primary)

    def test_no_bridge_ships_empty_table(self, tmp_path, pinned_snapshot):
        """Without a bridge the table is empty but present and conforming."""
        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        assert result["posts"].schema == POSTS_SCHEMA
        assert result["posts"].height == 0
        assert result["metadata"]["post_count"] == 0
        assert result["metadata"]["posts_processed_at"] is None

    def test_publishes_threads_and_receipt_posts(self, tmp_path, pinned_snapshot):
        """The threads ship, plus the post LeBron's receipt lives in; the
        rest of the bridge stays in reference/."""
        _write_game_logs(pinned_snapshot)
        _write_posts_bridge(
            pinned_snapshot,
            [
                self._row("t3_gt", "game_thread", "0022500001", True),
                self._row("t3_post123", "other", None, False),
                self._row("t3_noise", "other", None, False),
            ],
        )

        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        assert result["posts"]["post_id"].to_list() == ["t3_gt", "t3_post123"]
        assert result["metadata"]["post_count"] == 2
        assert result["metadata"]["posts_processed_at"] == "2026-09-13"


def _fact(rows: list[tuple[str, str | None, str]]) -> pl.DataFrame:
    """A usable fact frame from (link_id, attributed_player, sentiment)
    triples — the columns compute_game_sentiment reads. player_id is
    assigned per distinct player in order of appearance."""
    ids = {p: i + 1 for i, p in enumerate(dict.fromkeys(r[1] for r in rows if r[1]))}
    return pl.DataFrame(
        {
            "link_id": [r[0] for r in rows],
            "attributed_player": [r[1] for r in rows],
            "player_id": [ids.get(r[1]) for r in rows],
            "sentiment": [r[2] for r in rows],
        },
        schema={
            "link_id": pl.String,
            "attributed_player": pl.String,
            "player_id": pl.Int64,
            "sentiment": pl.String,
        },
    )


class TestComputeGameSentiment:
    """Tests for the Player x Game rollup through the bridge."""

    @pytest.fixture
    def posts(self):
        """Game 1's two threads, an unlinked post, and game 2's thread."""
        return pl.DataFrame(
            [
                _post_row("t3_gt1", "game_thread", "G1", True),
                _post_row("t3_pgt1", "post_game_thread", "G1", True),
                _post_row("t3_news", "other", None, False),
                _post_row("t3_gt2", "game_thread", "G2", True),
            ],
            schema=POSTS_SCHEMA,
        )

    def test_merges_a_games_threads(self, posts):
        """The game and post-game threads roll up to one row per player x game."""
        df = _fact(
            [
                ("t3_gt1", "LeBron James", "neg"),
                ("t3_pgt1", "LeBron James", "pos"),
                ("t3_pgt1", "LeBron James", "neg"),
            ]
        )

        result = compute_game_sentiment(df, posts)

        assert result.height == 1
        row = result.row(0, named=True)
        assert (row["attributed_player"], row["game_id"]) == ("LeBron James", "G1")
        assert (row["neg_count"], row["pos_count"], row["comment_count"]) == (2, 1, 3)
        assert row["neg_rate"] == 0.6667

    def test_drops_rows_outside_a_games_threads(self, posts):
        """A comment in a non-game post, or in a post the bridge never saw,
        reaches no game."""
        df = _fact(
            [
                ("t3_gt1", "LeBron James", "neg"),
                ("t3_news", "LeBron James", "neg"),
                ("t3_unknown", "LeBron James", "neg"),
            ]
        )

        result = compute_game_sentiment(df, posts)

        assert result["game_id"].to_list() == ["G1"]
        assert result["comment_count"].to_list() == [1]

    def test_thread_comment_count_is_the_games_usable_rows(self, posts):
        """The room size counts every fact row in the game's threads —
        other players and unattributed rows included — and repeats per
        player row; the measures count only the player's own rows."""
        df = _fact(
            [
                ("t3_gt1", "LeBron James", "neg"),
                ("t3_pgt1", "LeBron James", "pos"),
                ("t3_gt1", "Giannis Antetokounmpo", "neu"),
                ("t3_pgt1", None, "neg"),
                ("t3_gt2", "LeBron James", "pos"),
            ]
        )

        result = compute_game_sentiment(df, posts)

        by_key = {(r["attributed_player"], r["game_id"]): r for r in result.to_dicts()}
        assert set(by_key) == {
            ("Giannis Antetokounmpo", "G1"),
            ("LeBron James", "G1"),
            ("LeBron James", "G2"),
        }
        assert by_key[("LeBron James", "G1")]["comment_count"] == 2
        assert by_key[("Giannis Antetokounmpo", "G1")]["comment_count"] == 1
        assert by_key[("LeBron James", "G1")]["thread_comment_count"] == 4
        assert by_key[("Giannis Antetokounmpo", "G1")]["thread_comment_count"] == 4
        assert by_key[("LeBron James", "G2")]["thread_comment_count"] == 1

    def test_conforms_and_sorts_by_player_then_game(self, posts):
        """The frame is the contract, ordered by (attributed_player, game_id)."""
        df = _fact(
            [
                ("t3_gt2", "LeBron James", "pos"),
                ("t3_gt1", "LeBron James", "neg"),
                ("t3_gt1", "Giannis Antetokounmpo", "neu"),
            ]
        )

        result = compute_game_sentiment(df, posts)

        assert result.schema == GAME_SENTIMENT_SCHEMA
        assert result.select("attributed_player", "game_id").rows() == [
            ("Giannis Antetokounmpo", "G1"),
            ("LeBron James", "G1"),
            ("LeBron James", "G2"),
        ]

    def test_empty_posts_gives_empty_conforming_view(self):
        """Without a bridge the view is empty but keeps its contract."""
        df = _fact([("t3_gt1", "LeBron James", "neg")])

        result = compute_game_sentiment(df, pl.DataFrame(schema=POSTS_SCHEMA))

        assert result.height == 0
        assert result.schema == GAME_SENTIMENT_SCHEMA


class TestAggregateGameSentiment:
    """Tests for the view's passage through aggregate_sentiment."""

    def test_no_bridge_ships_empty_view(self, tmp_path, pinned_snapshot):
        """Without a bridge the view is empty but present and conforming."""
        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        assert result["game_sentiment"].schema == GAME_SENTIMENT_SCHEMA
        assert result["game_sentiment"].height == 0

    def test_rolls_the_fact_up_through_the_published_posts(
        self, tmp_path, pinned_snapshot
    ):
        """LeBron's comment in the game thread lands on the game; his other
        comment, in a non-game post, does not — so the view's total per
        player never exceeds player_overall's."""
        _write_game_logs(pinned_snapshot)
        _write_posts_bridge(
            pinned_snapshot,
            [
                _post_row("t3_post123", "game_thread", "0022500001", True),
                _post_row("t3_post456", "other", None, False),
            ],
        )

        result = aggregate_sentiment(_lebron_parquet(tmp_path))

        view = result["game_sentiment"]
        assert view.to_dicts() == [
            {
                "attributed_player": "LeBron James",
                "player_id": 2544,
                "game_id": "0022500001",
                "neg_count": 0,
                "pos_count": 1,
                "neu_count": 0,
                "comment_count": 1,
                "neg_rate": 0.0,
                "pos_rate": 1.0,
                "net_sentiment": 1.0,
                "polarization": 1.0,
                "thread_comment_count": 1,
            }
        ]
        per_player = view.group_by("attributed_player").agg(
            pl.col("comment_count").sum()
        )
        totals = result["player_overall"].select("attributed_player", "comment_count")
        joined = per_player.join(totals, on="attributed_player", suffix="_overall")
        assert (joined["comment_count"] <= joined["comment_count_overall"]).all()
