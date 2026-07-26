"""Tests for pipeline/results.py sentiment frame assembly."""

import json
from pathlib import Path

import polars as pl
import pytest

from pipeline.results import build_sentiment_dataframe
from pipeline.schemas import COMMENT_INPUT_SCHEMA, SENTIMENT_SCHEMA


def _succeeded(
    custom_id: str, content: str, input_tokens: int = 100, output_tokens: int = 20
) -> dict:
    """Build a succeeded entry shaped like download_results output."""
    return {
        "custom_id": custom_id,
        "result_type": "succeeded",
        "content": content,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _errored(custom_id: str) -> dict:
    """Build an errored entry shaped like download_results output."""
    return {
        "custom_id": custom_id,
        "result_type": "errored",
        "error": "api_error: Overloaded",
    }


def _write_results_file(responses_dir: Path, entries: list[dict]) -> None:
    """Write entries as a batch results JSONL file."""
    responses_dir.mkdir(exist_ok=True)
    path = responses_dir / "batch_001_results.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")


@pytest.fixture
def filtered_comments_file(
    tmp_path, valid_nba_comment, valid_team_subreddit_comment
) -> Path:
    """
    Two filtered comments as JSONL (ids abc123 and def456).

    Composes the conftest raw-comment fixtures with mentioned_players,
    the field the filter stage appends before classification.
    """
    comments = [
        {**valid_nba_comment, "mentioned_players": ["LeBron James"]},
        {**valid_team_subreddit_comment, "mentioned_players": ["Jayson Tatum"]},
    ]
    path = tmp_path / "filtered.jsonl"
    path.write_text("\n".join(json.dumps(comment) for comment in comments) + "\n")
    return path


@pytest.fixture
def responses_dir(tmp_path, valid_sentiment_responses) -> Path:
    """
    Responses dir with one results file where both comments succeeded.

    Reuses raw response strings from the conftest sentiment fixture;
    custom_ids match the filtered_comments_file comment ids.
    """
    raw_responses = [raw for raw, _ in valid_sentiment_responses]
    directory = tmp_path / "responses"
    _write_results_file(
        directory,
        [
            _succeeded("abc123", raw_responses[0]),  # pos, 0.95, LeBron James
            _succeeded("def456", raw_responses[2], 80, 15),  # neu, 0.6, null
        ],
    )
    return directory


class TestBuildSentimentDataframe:
    """Tests for joining batch results with filtered comments."""

    def test_assembled_frame_matches_sentiment_schema(
        self, responses_dir, filtered_comments_file
    ):
        """Verify the assembled frame conforms to SENTIMENT_SCHEMA."""
        # Act
        df, _ = build_sentiment_dataframe(responses_dir, filtered_comments_file)

        # Assert
        assert df.schema == SENTIMENT_SCHEMA
        assert df.height == 2

    def test_joined_values_match_inputs(self, responses_dir, filtered_comments_file):
        """Verify joined row values carry through from both inputs."""
        # Act
        df, _ = build_sentiment_dataframe(responses_dir, filtered_comments_file)

        # Assert
        row = df.filter(df["comment_id"] == "abc123").to_dicts()[0]
        assert row["body"] == "LeBron is washed, can't believe we traded for him"
        assert row["sentiment"] == "pos"
        assert row["confidence"] == 0.95
        assert row["sentiment_player"] == "LeBron James"
        assert row["input_tokens"] == 100
        assert row["output_tokens"] == 20

    def test_link_id_carried_from_filtered_comments(
        self, responses_dir, filtered_comments_file
    ):
        """Verify link_id flows from the filtered NDJSON into the frame (#43)."""
        # Act
        df, _ = build_sentiment_dataframe(responses_dir, filtered_comments_file)

        # Assert
        link_ids = dict(zip(df["comment_id"].to_list(), df["link_id"].to_list()))
        assert link_ids == {"abc123": "t3_post123", "def456": "t3_post456"}
        assert df["link_id"].null_count() == 0

    def test_empty_results_yield_empty_conformant_frame(
        self, tmp_path, filtered_comments_file
    ):
        """Verify an all-errored batch produces a 0-row frame with the full schema."""
        # Arrange
        directory = tmp_path / "responses"
        _write_results_file(directory, [_errored("abc123"), _errored("def456")])

        # Act
        df, failed = build_sentiment_dataframe(directory, filtered_comments_file)

        # Assert
        assert df.height == 0
        assert df.schema == SENTIMENT_SCHEMA
        assert len(failed) == 2

    def test_failed_requests_separated_from_results(
        self, tmp_path, filtered_comments_file, valid_sentiment_responses
    ):
        """Verify errored entries land in failed_requests, not the frame."""
        # Arrange
        raw_responses = [raw for raw, _ in valid_sentiment_responses]
        directory = tmp_path / "responses"
        _write_results_file(
            directory,
            [_succeeded("abc123", raw_responses[0]), _errored("def456")],
        )

        # Act
        df, failed = build_sentiment_dataframe(directory, filtered_comments_file)

        # Assert
        assert df.height == 1
        assert df["comment_id"].to_list() == ["abc123"]
        assert len(failed) == 1
        assert failed[0]["custom_id"] == "def456"

    def test_list_valued_p_normalizes_to_null_player(
        self, tmp_path, filtered_comments_file
    ):
        """Verify a list-valued p row assembles with a null sentiment_player (#71).

        The schema equality also pins the explicit row projection: the
        p_raw signal from parse_response must never reach the frame.
        """
        # Arrange
        directory = tmp_path / "responses"
        _write_results_file(
            directory,
            [
                _succeeded(
                    "abc123", '{"s": "neg", "c": 0.85, "p": ["Julian", "Keldon"]}'
                )
            ],
        )

        # Act
        df, failed = build_sentiment_dataframe(directory, filtered_comments_file)

        # Assert
        assert df.height == 1
        row = df.to_dicts()[0]
        assert row["sentiment"] == "neg"
        assert row["sentiment_player"] is None
        assert df.schema == SENTIMENT_SCHEMA
        assert failed == []

    def test_missing_results_files_raise_file_not_found(
        self, tmp_path, filtered_comments_file
    ):
        """Verify an empty responses dir fails fast."""
        # Arrange
        directory = tmp_path / "responses"
        directory.mkdir()

        # Act / Assert
        with pytest.raises(FileNotFoundError, match="No results files"):
            build_sentiment_dataframe(directory, filtered_comments_file)

    def test_malformed_results_json_raises_with_filename(
        self, tmp_path, filtered_comments_file
    ):
        """Verify a corrupted results file fails fast naming the file."""
        # Arrange
        directory = tmp_path / "responses"
        directory.mkdir()
        (directory / "batch_001_results.jsonl").write_text("{not valid json\n")

        # Act / Assert
        with pytest.raises(ValueError, match="batch_001_results.jsonl"):
            build_sentiment_dataframe(directory, filtered_comments_file)

    def test_construction_drift_raises_at_boundary(
        self, monkeypatch, responses_dir, filtered_comments_file
    ):
        """Verify the write-boundary guard fires if construction drifts.

        Simulates a future edit that changes a construction-side schema
        without updating SENTIMENT_SCHEMA — the strict boundary check
        must catch the divergence rather than write a drifted parquet.
        """
        # Arrange
        drifted = pl.Schema(
            {
                name: (pl.Int32 if name == "score" else dtype)
                for name, dtype in COMMENT_INPUT_SCHEMA.items()
            }
        )
        monkeypatch.setattr("pipeline.results.COMMENT_INPUT_SCHEMA", drifted)

        # Act / Assert
        with pytest.raises(ValueError, match="sentiment.parquet") as exc:
            build_sentiment_dataframe(responses_dir, filtered_comments_file)
        assert "score" in str(exc.value)
