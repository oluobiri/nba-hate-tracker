"""Tests for pipeline/schemas.py schema validation."""

import polars as pl
import pytest

from pipeline.schemas import (
    AGGREGATE_VIEW_SCHEMAS,
    COMMENT_INPUT_SCHEMA,
    COMMENT_SAMPLES_SCHEMA,
    DASHBOARD_OUTPUT_SCHEMAS,
    PLAYERS_SCHEMA,
    PLAYERS_SNAPSHOT_COLUMNS,
    ROSTERS_SCHEMA,
    SENTIMENT_SCHEMA,
    TEAMS_SCHEMA,
    validate_schema,
)


@pytest.fixture
def sentiment_frame() -> pl.DataFrame:
    """One-row DataFrame conforming exactly to SENTIMENT_SCHEMA."""
    return pl.DataFrame(
        [
            {
                "comment_id": "abc123",
                "body": "LeBron is washed",
                "author": "user123",
                "author_flair_text": "Lakers",
                "author_flair_css_class": "lakers",
                "created_utc": 1709251200,
                "score": 10,
                "link_id": "t3_post123",
                "mentioned_players": ["LeBron James"],
                "sentiment": "neg",
                "confidence": 0.95,
                "sentiment_player": "LeBron James",
                "input_tokens": 100,
                "output_tokens": 20,
            }
        ],
        schema=SENTIMENT_SCHEMA,
    )


class TestLinkIdContract:
    """Contract guards for link_id, the v3 game-thread bridge field (#43)."""

    def test_sentiment_schema_pins_link_id_as_string(self):
        """Verify link_id is part of the sentiment.parquet contract."""
        assert SENTIMENT_SCHEMA["link_id"] == pl.String

    def test_comment_input_schema_reads_link_id(self):
        """Verify the filtered-NDJSON projection carries link_id."""
        assert COMMENT_INPUT_SCHEMA["link_id"] == pl.String


@pytest.fixture
def roster_frame(lebron_roster_row) -> pl.DataFrame:
    """One-row DataFrame conforming exactly to ROSTERS_SCHEMA."""
    return pl.DataFrame([lebron_roster_row], schema=ROSTERS_SCHEMA)


class TestPlayersContract:
    """Contract guards for the Player dimension (players.parquet)."""

    def test_roster_team_is_role_marked(self):
        """Verify the roster column is role-marked from birth — never bare `team`."""
        assert PLAYERS_SCHEMA["roster_team"] == pl.String
        assert "team" not in PLAYERS_SCHEMA.names()

    def test_excludes_rejected_columns(self):
        """Verify decided-out columns stay out (logo_url, age, snapshot team fields)."""
        for col in ("logo_url", "age", "player_name", "team_name", "team_abbr"):
            assert col not in PLAYERS_SCHEMA.names()

    def test_snapshot_side_dtypes_derive_from_rosters(self):
        """Verify snapshot-side dtypes match ROSTERS_SCHEMA exactly (no drift)."""
        for col in PLAYERS_SNAPSHOT_COLUMNS:
            assert PLAYERS_SCHEMA[col] == ROSTERS_SCHEMA[col]

    def test_dashboard_outputs_superset(self):
        """Verify the output mapping is views + the dimensions, and views stay fact-only."""
        assert set(DASHBOARD_OUTPUT_SCHEMAS) == set(AGGREGATE_VIEW_SCHEMAS) | {
            "players",
            "teams",
        }
        assert DASHBOARD_OUTPUT_SCHEMAS["players"] is PLAYERS_SCHEMA
        assert "players" not in AGGREGATE_VIEW_SCHEMAS


class TestTeamsContract:
    """Contract guards for the Team dimension (teams.parquet)."""

    def test_pins_column_set_and_dtypes(self):
        """Verify the spec §3 column set with pinned dtypes."""
        assert TEAMS_SCHEMA == pl.Schema(
            {
                "team": pl.String,
                "abbreviation": pl.String,
                "conference": pl.String,
                "team_id": pl.Int64,
                "logo_url": pl.String,
            }
        )

    def test_pk_is_unmarked_team(self):
        """Verify the dimension's own key is bare `team` — role-marking
        (roster_team/fan_team) applies to FK columns on fact tables."""
        assert TEAMS_SCHEMA.names()[0] == "team"
        assert "fan_team" not in TEAMS_SCHEMA.names()

    def test_joins_outputs_but_not_views(self):
        """Verify teams ships via DASHBOARD_OUTPUT_SCHEMAS only — a
        dimension, not a fact rollup; the views mapping stays fact-only."""
        assert DASHBOARD_OUTPUT_SCHEMAS["teams"] is TEAMS_SCHEMA
        assert "teams" not in AGGREGATE_VIEW_SCHEMAS


class TestCommentSamplesContract:
    """Contract guards for the comment-samples fact subset (comment_samples.parquet)."""

    def test_pins_column_set_and_dtypes(self):
        """Verify the decided column set with pinned dtypes, in order."""
        assert COMMENT_SAMPLES_SCHEMA == pl.Schema(
            {
                "attributed_player": pl.String,
                "sentiment": pl.String,
                "rank": pl.Int64,
                "comment_id": pl.String,
                "link_id": pl.String,
                "body": pl.String,
                "score": pl.Int64,
                "created_utc": pl.Int64,
                "fan_team": pl.String,
            }
        )

    def test_fan_team_is_role_marked(self):
        """Verify the fan-role Team FK is role-marked from birth — no
        unmarked `team` column on a new produced file."""
        assert "fan_team" in COMMENT_SAMPLES_SCHEMA.names()
        assert "team" not in COMMENT_SAMPLES_SCHEMA.names()

    def test_excludes_rejected_columns(self):
        """Verify decided-out columns stay out (author, confidence)."""
        for col in ("author", "confidence"):
            assert col not in COMMENT_SAMPLES_SCHEMA.names()

    def test_fact_side_dtypes_derive_from_sentiment(self):
        """Verify every column carried verbatim from the fact keeps the
        fact's dtype (no drift between the subset and its source)."""
        for col in ("comment_id", "link_id", "body", "score", "created_utc"):
            assert COMMENT_SAMPLES_SCHEMA[col] == SENTIMENT_SCHEMA[col]


class TestRostersContract:
    """Contract guards for the roster snapshot reference asset."""

    def test_conforming_frame_passes(self, roster_frame):
        """Verify a frame matching ROSTERS_SCHEMA validates without raising."""
        validate_schema(roster_frame, ROSTERS_SCHEMA, "rosters.parquet")

    def test_pins_height_and_weight(self):
        """Verify the bio columns are in the contract (the re-snapshot's point)."""
        assert ROSTERS_SCHEMA["height"] == pl.String
        assert ROSTERS_SCHEMA["weight"] == pl.String

    def test_birth_date_is_date_typed(self):
        """Verify birth_date lands as a real Date, not the endpoint's raw string."""
        assert ROSTERS_SCHEMA["birth_date"] == pl.Date


class TestValidateSchema:
    """Tests for validate_schema fail-fast behavior and diagnostics."""

    def test_conforming_frame_passes(self, sentiment_frame):
        """Verify a frame matching the schema validates without raising."""
        # Arrange / Act / Assert — no exception is the assertion
        validate_schema(sentiment_frame, SENTIMENT_SCHEMA, "sentiment.parquet")

    def test_missing_column_raises(self, sentiment_frame):
        """Verify a dropped column is reported by name."""
        # Arrange
        df = sentiment_frame.drop("score")

        # Act / Assert
        with pytest.raises(ValueError, match="sentiment.parquet") as exc:
            validate_schema(df, SENTIMENT_SCHEMA, "sentiment.parquet")
        assert "missing columns" in str(exc.value)
        assert "score" in str(exc.value)

    def test_extra_column_raises(self, sentiment_frame):
        """Verify an unexpected column is reported by name."""
        # Arrange
        df = sentiment_frame.with_columns(pl.lit(1).alias("bonus"))

        # Act / Assert
        with pytest.raises(ValueError, match="sentiment.parquet") as exc:
            validate_schema(df, SENTIMENT_SCHEMA, "sentiment.parquet")
        assert "extra columns" in str(exc.value)
        assert "bonus" in str(exc.value)

    def test_dtype_mismatch_raises(self, sentiment_frame):
        """Verify a wrong dtype is reported with expected and actual types."""
        # Arrange
        df = sentiment_frame.with_columns(pl.col("score").cast(pl.Int32))

        # Act / Assert
        with pytest.raises(ValueError, match="sentiment.parquet") as exc:
            validate_schema(df, SENTIMENT_SCHEMA, "sentiment.parquet")
        message = str(exc.value)
        assert "score" in message
        assert "Int64" in message
        assert "Int32" in message

    def test_column_order_mismatch_raises(self, sentiment_frame):
        """Verify reordered columns fail with an order-specific diagnostic."""
        # Arrange
        df = sentiment_frame.select(list(reversed(SENTIMENT_SCHEMA.names())))

        # Act / Assert
        with pytest.raises(ValueError, match="sentiment.parquet") as exc:
            validate_schema(df, SENTIMENT_SCHEMA, "sentiment.parquet")
        assert "column order" in str(exc.value)
