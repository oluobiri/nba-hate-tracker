"""Unit tests for extract_filter module."""

import pytest

from scripts.extract_filter import is_target_subreddit, has_valid_body

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
