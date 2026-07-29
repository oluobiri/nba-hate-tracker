"""Tests for pipeline/schemas.py schema validation."""

from datetime import date

import polars as pl
import pytest

from pipeline.schemas import (
    COMMENT_INPUT_SCHEMA,
    ROSTERS_SCHEMA,
    SENTIMENT_SCHEMA,
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
def roster_frame() -> pl.DataFrame:
    """One-row DataFrame conforming exactly to ROSTERS_SCHEMA."""
    return pl.DataFrame(
        [
            {
                "player_id": 2544,
                "player_name": "LeBron James",
                "team_name": "Los Angeles Lakers",
                "team_abbr": "LAL",
                "jersey_number": "23",
                "position": "F",
                "height": "6-9",
                "weight": "250",
                "age": 40,
                "experience": "21",
                "birth_date": date(1984, 12, 30),
                "school": "St. Vincent-St. Mary HS (OH)",
            }
        ],
        schema=ROSTERS_SCHEMA,
    )


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
