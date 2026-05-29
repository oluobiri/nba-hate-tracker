"""Unit tests for pipeline.processors module."""

import logging

from pipeline.processors import (
    ProcessingStats,
    extract_fields,
    has_valid_body,
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
