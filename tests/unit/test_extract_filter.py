"""Unit tests for extract_filter module."""

import pytest

from scripts.extract_filter import (
    ProcessingStats,
    is_target_subreddit, 
    has_valid_body,
    extract_fields,
    parse_json_line,
    process_comment
)

class TestIsTargetSubreddit:
    """Tests for subreddit filtering logic."""

    def test_nba_subreddit_is_valid(self, valid_nba_comment):
        """Main r/nba subreddit should be accepted."""
        assert is_target_subreddit(valid_nba_comment) is True

    def test_team_subreddit_is_valid(self, valid_team_subreddit_comment):
        """Team-specific subreddits should be accepted."""
        assert is_target_subreddit(valid_team_subreddit_comment)

    def test_wrong_subreddit_rejected(self, wrong_subreddit_comment):
        """Non-NBA subreddits should be rejected."""
        assert is_target_subreddit(wrong_subreddit_comment) is False

    def test_uppercase_subreddit_still_valid(self, uppercase_subreddit_comment):
        """Subreddit matching should be case-insensitive."""
        assert is_target_subreddit(uppercase_subreddit_comment) is True

    def test_missing_subreddit_field_rejected(self):
        """Comment with no subreddit field should be rejected."""
        comment = {"id": "test", "body": "hello"}
        assert is_target_subreddit(comment) is False

class TestHasValidBody:
    """Tests for valid body filtering logic."""

    def test_valid_nba_comment_is_valid(self, valid_nba_comment):
        """Valid r/nba comments should be accepted"""
        assert has_valid_body(valid_nba_comment) is True

    def test_missing_body_comment_is_rejected(self, missing_body_comment):
        """Comments with no body key should be rejected."""
        assert has_valid_body(missing_body_comment) is False

    def test_empty_body_comment_is_rejected(self, empty_body_comment):
        """Comments with empty strung bodies should be rejected."""
        assert has_valid_body(empty_body_comment) is False

    def test_deleted_body_comment_is_rejected(self, deleted_body_comment):
        """Comments that have been deleted should be rejected."""
        assert has_valid_body(deleted_body_comment) is False

    def test_removed_comment_is_rejected(self):
        """Comments that have been removed should be rejected."""
        comment = {"id": "test", "body": "[removed]"}
        assert has_valid_body(comment) is False

class TestExtractFields:
    """Tests for field extraction logic."""

    def test_extracts_all_fields(self, valid_nba_comment):
        """All expected fields should be present in output."""
        result = extract_fields(valid_nba_comment)

        expected_keys = {
            "id",
            "body",
            "author",
            "author_flair_text",
            "author_flair_css_class",
            "subreddit",
            "created_utc",
            "score",
            "controversiality",
            "parent_id",
            "link_id",
        }
        assert set(result.keys()) == expected_keys

    def test_preserves_field_values(self, valid_nba_comment):
        """Field values should match input."""
        result = extract_fields(valid_nba_comment)

        assert result["id"] == "abc123"
        assert result["body"] == "LeBron is washed, can't believe we traded for him"
        assert result["subreddit"] == "nba"
        assert result["score"] == 42

    def test_missing_optional_fields_become_none(self):
        """Missing optional fields should be None, not raise errors."""
        minimal_comment = {
            "id": "test123",
            "body": "test body",
            "subreddit": "nba",
            "created_utc": 1234567890,
        }
        result = extract_fields(minimal_comment)

        assert result["id"] == "test123"
        assert result["author"] is None
        assert result["author_flair_text"] is None
        assert result["score"] is None

    def test_extra_fields_ignored(self):
        """Fields not in our schema should not appear in output."""
        comment_with_extras = {
            "id": "test",
            "body": "test",
            "subreddit": "nba",
            "created_utc": 123,
            "extra_field": "should not appear",
            "another_extra": 999,
            "gilded": 5,
        }
        result = extract_fields(comment_with_extras)

        assert "extra_field" not in result
        assert "another_extra" not in result
        assert "gilded" not in result

class TestParseJsonLine:
    """Tests for JSON parsing."""

    def test_valid_json_parsed(self):
        """Valid JSON string should parse correctly."""
        line = '{"id": "test", "body": "hello"}'
        result = parse_json_line(line)

        assert result == {"id": "test", "body": "hello"}

    def test_invalid_json_returns_none(self):
        """Invalid JSON should return None, not raise."""
        line = "this is not json"
        result = parse_json_line(line)

        assert result is None

    def test_incomplete_json_returns_none(self):
        """Incomplete JSON should return None."""
        line = '{"id": "test", "body":'
        result = parse_json_line(line)

        assert result is None

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        result = parse_json_line("")

        assert result is None

class TestProcessingStats:
    """Tests for statistics tracking."""

    def test_initial_values(self):
        """Stats should initialize to zero."""
        stats = ProcessingStats()

        assert stats.total_processed == 0
        assert stats.accepted == 0
        assert stats.rejected_subreddit == 0
        assert stats.rejected_body == 0
        assert stats.rejected_malformed == 0

    def test_total_rejected_calculation(self):
        """Total rejected should sum all rejection reasons."""
        stats = ProcessingStats(
            rejected_subreddit=100,
            rejected_body=50,
            rejected_malformed=10,
        )

        assert stats.total_rejected == 160

class TestProcessComment:
    """Tests for the full comment processing pipeline."""

    def test_valid_comment_accepted(self, valid_nba_comment):
        """Valid NBA comment should be accepted and extracted."""
        stats = ProcessingStats()
        result = process_comment(valid_nba_comment, stats)

        assert result is not None
        assert result["id"] == "abc123"
        assert stats.accepted == 1
        assert stats.total_processed == 1

    def test_wrong_subreddit_rejected(self, wrong_subreddit_comment):
        """Comment from wrong subreddit should be rejected."""
        stats = ProcessingStats()
        result = process_comment(wrong_subreddit_comment, stats)

        assert result is None
        assert stats.rejected_subreddit == 1
        assert stats.accepted == 0

    def test_missing_body_rejected(self, missing_body_comment):
        """Comment with missing body should be rejected."""
        stats = ProcessingStats()
        result = process_comment(missing_body_comment, stats)

        assert result is None
        assert stats.rejected_body == 1

    def test_subreddit_checked_before_body(self):
        """Subreddit filter should run before body filter.
        
        This matters for accurate rejection stats — a comment from r/soccer
        with a deleted body should count as rejected_subreddit, not rejected_body.
        """
        comment = {
            "subreddit": "soccer",
            "body": "[deleted]",
        }
        stats = ProcessingStats()
        result = process_comment(comment, stats)

        assert result is None
        assert stats.rejected_subreddit == 1
        assert stats.rejected_body == 0

    def test_batch_processing_stats(self, mixed_comments_batch):
        """Processing multiple comments should accumulate stats correctly."""
        stats = ProcessingStats()

        results = [process_comment(c, stats) for c in mixed_comments_batch]

        # From fixture: 2 valid (nba, bostonceltics), 1 wrong sub, 1 missing body
        assert stats.total_processed == 4 
        assert stats.accepted == 2
        assert stats.rejected_subreddit == 1
        assert stats.rejected_body == 1