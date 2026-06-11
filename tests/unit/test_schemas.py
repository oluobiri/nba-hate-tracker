"""Tests for pipeline/schemas.py schema validation."""

import polars as pl
import pytest

from pipeline.schemas import SENTIMENT_SCHEMA, validate_schema


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
