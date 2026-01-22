"""Unit tests for extract_filter module."""

from scripts.extract_filter import (
    is_target_subreddit,
    parse_json_line,
    log_stats_summary,
)
from pipeline.processors import CommentPipeline, has_valid_body, extract_fields


class TestIsTargetSubreddit:
    """Tests for subreddit filtering logic."""

    def test_nba_subreddit_is_valid(self, valid_nba_comment):
        """Main r/nba subreddit should be accepted."""
        result = is_target_subreddit(valid_nba_comment)
        assert result is not None
        assert result == valid_nba_comment

    def test_team_subreddit_is_valid(self, valid_team_subreddit_comment):
        """Team-specific subreddits should be accepted."""
        result = is_target_subreddit(valid_team_subreddit_comment)
        assert result is not None

    def test_wrong_subreddit_rejected(self, wrong_subreddit_comment):
        """Non-NBA subreddits should be rejected."""
        assert is_target_subreddit(wrong_subreddit_comment) is None

    def test_uppercase_subreddit_still_valid(self, uppercase_subreddit_comment):
        """Subreddit matching should be case-insensitive."""
        result = is_target_subreddit(uppercase_subreddit_comment)
        assert result is not None

    def test_missing_subreddit_field_rejected(self):
        """Comment with no subreddit field should be rejected."""
        comment = {"id": "test", "body": "hello"}
        assert is_target_subreddit(comment) is None


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


class TestLogStatsSummary:
    """Tests for log_stats_summary function."""

    def test_logs_stats_without_error(self, caplog):
        """log_stats_summary should log without raising errors."""
        import logging

        stats = {
            "total": 100,
            "accepted": 50,
            "rejected_is_target_subreddit": 30,
            "rejected_has_valid_body": 20,
        }

        with caplog.at_level(logging.INFO):
            log_stats_summary(stats)

        assert "Total processed:" in caplog.text
        assert "Accepted:" in caplog.text
        assert "Acceptance rate:" in caplog.text


class TestPipelineIntegration:
    """Tests for the full comment processing pipeline using CommentPipeline."""

    def test_valid_comment_accepted(self, valid_nba_comment):
        """Valid NBA comment should be accepted and extracted."""
        pipeline = CommentPipeline()
        pipeline.add_step(is_target_subreddit)
        pipeline.add_step(has_valid_body)
        pipeline.add_step(extract_fields)

        result = pipeline.process(valid_nba_comment)

        assert result is not None
        assert result["id"] == "abc123"
        assert pipeline.stats["accepted"] == 1
        assert pipeline.stats["total"] == 1

    def test_wrong_subreddit_rejected(self, wrong_subreddit_comment):
        """Comment from wrong subreddit should be rejected."""
        pipeline = CommentPipeline()
        pipeline.add_step(is_target_subreddit)
        pipeline.add_step(has_valid_body)
        pipeline.add_step(extract_fields)

        result = pipeline.process(wrong_subreddit_comment)

        assert result is None
        assert pipeline.stats["rejected_is_target_subreddit"] == 1
        assert pipeline.stats["accepted"] == 0

    def test_missing_body_rejected(self, missing_body_comment):
        """Comment with missing body should be rejected."""
        pipeline = CommentPipeline()
        pipeline.add_step(is_target_subreddit)
        pipeline.add_step(has_valid_body)
        pipeline.add_step(extract_fields)

        result = pipeline.process(missing_body_comment)

        assert result is None
        assert pipeline.stats["rejected_has_valid_body"] == 1

    def test_subreddit_checked_before_body(self):
        """Subreddit filter should run before body filter.

        This matters for accurate rejection stats — a comment from r/soccer
        with a deleted body should count as rejected_is_target_subreddit,
        not rejected_has_valid_body.
        """
        comment = {
            "subreddit": "soccer",
            "body": "[deleted]",
        }
        pipeline = CommentPipeline()
        pipeline.add_step(is_target_subreddit)
        pipeline.add_step(has_valid_body)
        pipeline.add_step(extract_fields)

        result = pipeline.process(comment)

        assert result is None
        assert pipeline.stats["rejected_is_target_subreddit"] == 1
        assert pipeline.stats["rejected_has_valid_body"] == 0

    def test_batch_processing_stats(self, mixed_comments_batch):
        """Processing multiple comments should accumulate stats correctly."""
        pipeline = CommentPipeline()
        pipeline.add_step(is_target_subreddit)
        pipeline.add_step(has_valid_body)
        pipeline.add_step(extract_fields)

        results = [pipeline.process(c) for c in mixed_comments_batch]

        assert results is not None

        # From fixture: 2 valid (nba, bostonceltics), 1 wrong sub, 1 missing body
        assert pipeline.stats["total"] == 4
        assert pipeline.stats["accepted"] == 2
        assert pipeline.stats["rejected_is_target_subreddit"] == 1
        assert pipeline.stats["rejected_has_valid_body"] == 1
