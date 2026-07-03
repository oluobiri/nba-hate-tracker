"""Unit tests for pipeline.processors module."""

import json
import logging

import pytest

from pipeline.processors import (
    ProcessingStats,
    ensure_trailing_newline,
    extract_fields,
    has_valid_body,
    read_last_created_utc,
    resume_after,
)
from utils.constants import REQUIRED_FIELDS


class TestHasValidBody:
    """Tests for has_valid_body filter function."""

    def test_valid_body_returns_comment(self, valid_nba_comment):
        """Comment with valid body should be returned unchanged."""
        result = has_valid_body(valid_nba_comment)
        assert result == valid_nba_comment

    def test_missing_body_returns_none(self, missing_body_comment):
        """Comment with no body key should return None."""
        result = has_valid_body(missing_body_comment)
        assert result is None

    def test_empty_body_returns_none(self, empty_body_comment):
        """Comment with empty string body should return None."""
        result = has_valid_body(empty_body_comment)
        assert result is None

    def test_deleted_body_returns_none(self, deleted_body_comment):
        """Comment with [deleted] body should return None."""
        result = has_valid_body(deleted_body_comment)
        assert result is None

    def test_removed_body_returns_none(self):
        """Comment with [removed] body should return None."""
        comment = {"id": "test", "body": "[removed]"}
        result = has_valid_body(comment)
        assert result is None


class TestExtractFields:
    """Tests for extract_fields transform function."""

    def test_extracts_all_expected_fields(self, valid_nba_comment):
        """All REQUIRED_FIELDS should be present in output."""
        result = extract_fields(valid_nba_comment)

        assert set(result.keys()) == set(REQUIRED_FIELDS)

    def test_preserves_field_values(self, valid_nba_comment):
        """Field values should match input."""
        result = extract_fields(valid_nba_comment)

        assert result["id"] == valid_nba_comment["id"]
        assert result["body"] == valid_nba_comment["body"]
        assert result["score"] == valid_nba_comment["score"]

    def test_missing_fields_become_none(self):
        """Missing optional fields should be None."""
        minimal = {"id": "test", "body": "hello"}
        result = extract_fields(minimal)

        assert result["id"] == "test"
        assert result["author"] is None
        assert result["score"] is None

    def test_extra_fields_excluded(self):
        """Fields not in schema should not appear in output."""
        comment = {"id": "test", "body": "hi", "extra": "ignored", "gilded": 5}
        result = extract_fields(comment)

        assert "extra" not in result
        assert "gilded" not in result


class TestProcessingStats:
    """Tests for ProcessingStats dataclass."""

    def test_defaults_to_zero(self):
        """All fields default to 0."""
        stats = ProcessingStats()

        assert stats.total_comments == 0
        assert stats.accepted_comments == 0
        assert stats.rejected_body == 0
        assert stats.rejected_malformed == 0
        assert stats.rejected_no_player_mention == 0

    def test_rejected_comments_sums_all_rejections(self):
        """rejected_comments property sums the three rejection fields."""
        stats = ProcessingStats(
            rejected_body=10,
            rejected_malformed=5,
            rejected_no_player_mention=20,
        )

        assert stats.rejected_comments == 35

    def test_acceptance_rate_with_data(self):
        """acceptance_rate computes accepted/total."""
        stats = ProcessingStats(total_comments=100, accepted_comments=25)

        assert stats.acceptance_rate == 0.25

    def test_acceptance_rate_zero_total(self):
        """acceptance_rate returns 0.0 when no comments processed."""
        stats = ProcessingStats()

        assert stats.acceptance_rate == 0.0

    def test_log_summary_does_not_raise(self, caplog):
        """log_summary logs without errors."""
        stats = ProcessingStats(
            total_comments=100,
            accepted_comments=25,
            rejected_body=30,
            rejected_malformed=5,
            rejected_no_player_mention=40,
        )
        test_logger = logging.getLogger("test")

        with caplog.at_level(logging.INFO):
            stats.log_summary(test_logger)

        assert "Total processed:" in caplog.text
        assert "Acceptance rate:" in caplog.text


class TestReadLastCreatedUtc:
    """Tests for the read_last_created_utc download-resume helper."""

    def test_returns_last_line_timestamp(self, tmp_path):
        """Last valid line's created_utc should be returned."""
        path = tmp_path / "comments.jsonl"
        lines = [json.dumps({"id": str(i), "created_utc": 1000 + i}) for i in range(3)]
        path.write_text("\n".join(lines) + "\n")

        assert read_last_created_utc(path) == 1002

    def test_missing_file_returns_none(self, tmp_path):
        """Nonexistent file should return None (fresh start)."""
        assert read_last_created_utc(tmp_path / "missing.jsonl") is None

    def test_empty_file_returns_none(self, tmp_path):
        """Empty file should return None (fresh start)."""
        path = tmp_path / "empty.jsonl"
        path.touch()

        assert read_last_created_utc(path) is None

    def test_skips_truncated_final_line(self, tmp_path):
        """A mid-write truncated last line should fall back to the previous valid one."""
        path = tmp_path / "comments.jsonl"
        good = json.dumps({"id": "1", "created_utc": 1500})
        truncated = '{"id": "2", "created_utc": 16'
        path.write_text(good + "\n" + truncated)

        assert read_last_created_utc(path) == 1500

    def test_no_parseable_line_returns_none(self, tmp_path):
        """File with no valid JSON lines should return None."""
        path = tmp_path / "garbage.jsonl"
        path.write_text("not json\nalso not json\n")

        assert read_last_created_utc(path) is None

    def test_reads_only_tail_window(self, tmp_path):
        """Only the tail window is read; a partial first line in the window is skipped."""
        path = tmp_path / "comments.jsonl"
        filler = json.dumps({"id": "x", "created_utc": 1}) + "\n"
        last = json.dumps({"id": "last", "created_utc": 9999}) + "\n"
        path.write_text(filler * 5000 + last)

        assert read_last_created_utc(path, tail_bytes=1024) == 9999

    def test_float_created_utc_coerced_to_int(self, tmp_path):
        """Reddit sometimes serializes created_utc as a float; it should coerce to int."""
        path = tmp_path / "comments.jsonl"
        path.write_text(json.dumps({"id": "1", "created_utc": 1500.0}) + "\n")

        assert read_last_created_utc(path) == 1500


class TestResumeAfter:
    """Tests for the resume_after cursor resolver."""

    def test_missing_file_returns_none(self, tmp_path):
        """Nonexistent file should mean a fresh start."""
        assert resume_after(tmp_path / "missing.jsonl") is None

    def test_empty_file_returns_none(self, tmp_path):
        """Empty file should mean a fresh start."""
        path = tmp_path / "empty.jsonl"
        path.touch()

        assert resume_after(path) is None

    def test_returns_last_timestamp_plus_one(self, tmp_path):
        """Cursor should be last created_utc + 1, matching pagination semantics."""
        path = tmp_path / "comments.jsonl"
        path.write_text(json.dumps({"id": "1", "created_utc": 1500}) + "\n")

        assert resume_after(path) == 1501

    def test_unparseable_content_raises(self, tmp_path):
        """A file with data but no parseable resume point must raise, never signal fresh start."""
        path = tmp_path / "comments.jsonl"
        path.write_text("not json at all\n")

        with pytest.raises(ValueError, match="refusing to overwrite"):
            resume_after(path)

    def test_single_line_larger_than_tail_window_raises(self, tmp_path):
        """A line exceeding the tail window should raise, not signal fresh start."""
        path = tmp_path / "comments.jsonl"
        big = json.dumps({"id": "1", "created_utc": 1500, "body": "x" * 2048}) + "\n"
        path.write_text(big)

        with pytest.raises(ValueError, match="refusing to overwrite"):
            resume_after(path, tail_bytes=1024)


class TestEnsureTrailingNewline:
    """Tests for the ensure_trailing_newline append guard."""

    def test_appends_newline_when_missing(self, tmp_path):
        """File ending mid-line should gain a trailing newline."""
        path = tmp_path / "comments.jsonl"
        path.write_text('{"id": "1", "created_utc": 15')

        assert ensure_trailing_newline(path) is True
        assert path.read_text().endswith("\n")

    def test_noop_when_newline_present(self, tmp_path):
        """File already ending in a newline should be untouched."""
        path = tmp_path / "comments.jsonl"
        content = json.dumps({"id": "1", "created_utc": 1500}) + "\n"
        path.write_text(content)

        assert ensure_trailing_newline(path) is False
        assert path.read_text() == content

    def test_noop_on_missing_or_empty_file(self, tmp_path):
        """Missing and empty files need no guard, and a missing file must not be created."""
        missing = tmp_path / "missing.jsonl"
        assert ensure_trailing_newline(missing) is False
        assert not missing.exists()

        empty = tmp_path / "empty.jsonl"
        empty.touch()
        assert ensure_trailing_newline(empty) is False
