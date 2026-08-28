"""Tests for pipeline/results.py sentiment frame assembly."""

import json
import logging
from pathlib import Path

import polars as pl
import pytest

from pipeline.results import build_sentiment_dataframe, check_response_models
from pipeline.schemas import COMMENT_INPUT_SCHEMA, SENTIMENT_SCHEMA


def _succeeded(
    custom_id: str,
    content: str,
    input_tokens: int = 100,
    output_tokens: int = 20,
    model: str | None = None,
) -> dict:
    """Build a succeeded entry shaped like download_results output.

    model is optional: responses downloaded before #90 never persisted it.
    """
    entry = {
        "custom_id": custom_id,
        "result_type": "succeeded",
        "content": content,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if model is not None:
        entry["model"] = model
    return entry


def _errored(custom_id: str) -> dict:
    """Build an errored entry shaped like download_results output."""
    return {
        "custom_id": custom_id,
        "result_type": "errored",
        "error": "api_error: Overloaded",
    }


def _write_results_file(
    responses_dir: Path, entries: list[dict], batch_num: int = 1
) -> None:
    """Write entries as a batch results JSONL file."""
    responses_dir.mkdir(exist_ok=True)
    path = responses_dir / f"batch_{batch_num:03d}_results.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")


@pytest.fixture
def filtered_comments_file(
    tmp_path, valid_nba_comment, valid_team_subreddit_comment
) -> Path:
    """
    Two filtered comments as JSONL (ids abc123 and def456).

    Composes the conftest raw-comment fixtures with mentioned_players,
    the field the filter stage appends before classification. The values
    are deliberately wrong (pre-#54 stale-provenance simulation): assembly
    must ignore them and re-derive from body.
    """
    comments = [
        {**valid_nba_comment, "mentioned_players": ["Michael Jordan"]},
        {**valid_team_subreddit_comment, "mentioned_players": ["Stale Player"]},
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

    def test_mentions_rederived_from_body_not_ndjson(
        self, responses_dir, filtered_comments_file
    ):
        """Verify mentioned_players comes from body, not the NDJSON copy (#54).

        The fixture NDJSON carries deliberately wrong mentions; the
        assembled values must reflect the assembly-time season config.
        Real-config dependent: the fixture bodies must keep matching
        "LeBron James" / "Jayson Tatum" under the active players.yaml.
        """
        # Act
        df, _ = build_sentiment_dataframe(responses_dir, filtered_comments_file)

        # Assert
        mentions = dict(
            zip(df["comment_id"].to_list(), df["mentioned_players"].to_list())
        )
        assert mentions == {
            "abc123": ["LeBron James"],
            "def456": ["Jayson Tatum"],
        }

    def test_zero_mention_rows_kept_with_empty_list(
        self, tmp_path, valid_nba_comment, valid_team_subreddit_comment,
        valid_sentiment_responses,
    ):
        """Verify rows with no re-derived mentions stay in the frame (#54).

        Population is frozen at filter time ($-backed classifications);
        a row whose only filter-time match was contamination re-derives
        to an empty list, never drops.
        """
        # Arrange
        comments = [
            {**valid_nba_comment, "mentioned_players": ["Michael Jordan"]},
            {**valid_team_subreddit_comment, "mentioned_players": ["Stale Player"]},
            {
                **valid_nba_comment,
                "id": "ghi789",
                "body": "the refs decided this game",
                "mentioned_players": ["LeBron James"],  # contamination-only match
            },
        ]
        filtered_path = tmp_path / "filtered.jsonl"
        filtered_path.write_text(
            "\n".join(json.dumps(comment) for comment in comments) + "\n"
        )
        raw_responses = [raw for raw, _ in valid_sentiment_responses]
        directory = tmp_path / "responses"
        _write_results_file(
            directory,
            [
                _succeeded("abc123", raw_responses[0]),
                _succeeded("def456", raw_responses[2]),
                _succeeded("ghi789", raw_responses[2]),
            ],
        )

        # Act
        df, _ = build_sentiment_dataframe(directory, filtered_path)

        # Assert
        assert df.height == 3
        row = df.filter(df["comment_id"] == "ghi789").to_dicts()[0]
        assert row["mentioned_players"] == []

    def test_null_body_yields_null_mentions(
        self, tmp_path, valid_nba_comment, valid_sentiment_responses
    ):
        """Verify a null body maps to null mentions, not a crash.

        Polars map_elements skips nulls. Filtered data cannot contain
        null bodies (the filter stage requires a valid body); this test
        exists so a Polars behavior change is noticed, not to bless
        null bodies.
        """
        # Arrange
        comments = [{**valid_nba_comment, "body": None, "mentioned_players": []}]
        filtered_path = tmp_path / "filtered.jsonl"
        filtered_path.write_text(
            "\n".join(json.dumps(comment) for comment in comments) + "\n"
        )
        raw_responses = [raw for raw, _ in valid_sentiment_responses]
        directory = tmp_path / "responses"
        _write_results_file(directory, [_succeeded("abc123", raw_responses[0])])

        # Act
        df, _ = build_sentiment_dataframe(directory, filtered_path)

        # Assert
        assert df.height == 1
        assert df["mentioned_players"].to_list() == [None]

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

    def test_list_valued_p_normalization_logged(
        self, tmp_path, filtered_comments_file, caplog
    ):
        """Verify each normalization warns with custom_id and a count is logged.

        The WARNING lines are the observability channel for #71 (and the
        raw material for the #62 item-4 record), so their presence is
        pinned, not just the normalized values.
        """
        # Arrange
        directory = tmp_path / "responses"
        _write_results_file(
            directory,
            [
                _succeeded(
                    "abc123", '{"s": "neg", "c": 0.85, "p": ["Julian", "Keldon"]}'
                ),
                _succeeded("def456", '{"s": "pos", "c": 0.9, "p": ["Chet Holmgren"]}'),
            ],
        )

        # Act
        with caplog.at_level(logging.WARNING, logger="pipeline.results"):
            build_sentiment_dataframe(directory, filtered_comments_file)

        # Assert
        warnings = [
            record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ]
        assert any(
            "abc123" in message and "['Julian', 'Keldon']" in message
            for message in warnings
        )
        assert any(
            "def456" in message and "'Chet Holmgren'" in message
            for message in warnings
        )
        assert any("Normalized 2 list-valued p field(s)" in m for m in warnings)

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


class TestCheckResponseModels:
    """Tests for the response-side classifier identity cross-check."""

    def test_matching_model_passes(self, tmp_path):
        """Verify a model-bearing results file matching state is accepted."""
        directory = tmp_path / "responses"
        _write_results_file(
            directory,
            [
                _errored("aaa111"),
                _succeeded("abc123", '{"s":"pos","c":0.9,"p":null}', model="model-x"),
            ],
        )

        check_response_models(directory, "model-x")

    def test_mismatched_model_raises_naming_both(self, tmp_path):
        """Verify a response model differing from state fails loudly."""
        directory = tmp_path / "responses"
        _write_results_file(
            directory,
            [_succeeded("abc123", '{"s":"pos","c":0.9,"p":null}', model="model-y")],
        )

        with pytest.raises(RuntimeError, match="model-y.*model-x"):
            check_response_models(directory, "model-x")

    def test_model_free_file_is_skipped(self, tmp_path):
        """Verify pre-#90 responses (no model field anywhere) pass untouched."""
        directory = tmp_path / "responses"
        _write_results_file(
            directory,
            [_succeeded("abc123", '{"s":"pos","c":0.9,"p":null}'), _errored("def456")],
        )

        check_response_models(directory, "model-x")

    def test_mismatch_in_later_file_raises(self, tmp_path):
        """Verify every file is checked, not just the first."""
        directory = tmp_path / "responses"
        _write_results_file(
            directory,
            [_succeeded("abc123", '{"s":"pos","c":0.9,"p":null}', model="model-x")],
            batch_num=1,
        )
        _write_results_file(
            directory,
            [_succeeded("def456", '{"s":"neu","c":0.5,"p":null}', model="model-y")],
            batch_num=2,
        )

        with pytest.raises(RuntimeError, match="batch_002.*model-y"):
            check_response_models(directory, "model-x")

    def test_mismatch_past_line_cap_is_skipped(self, tmp_path):
        """Pin the 1000-line cap: a model echo past it is never scanned.

        The cap keeps field-free legacy files cheap to skip; this test
        locks the trade-off in so a refactor can't silently change it.
        """
        directory = tmp_path / "responses"
        entries = [_errored(f"e{i}") for i in range(1000)]
        entries.append(
            _succeeded("abc123", '{"s":"pos","c":0.9,"p":null}', model="model-y")
        )
        _write_results_file(directory, entries)

        check_response_models(directory, "model-x")

    def test_malformed_line_raises_with_filename(self, tmp_path):
        """Verify a malformed scanned line fails with file context."""
        directory = tmp_path / "responses"
        directory.mkdir()
        (directory / "batch_001_results.jsonl").write_text("not json\n")

        with pytest.raises(ValueError, match="Malformed JSON in batch_001"):
            check_response_models(directory, "model-x")
