"""
Tests for player mention matching logic.

Tests cover find_player_mentions, filter_player_mentions, and word boundary
handling.
"""

import pytest

from pipeline.processors import (
    find_player_matches,
    find_player_mentions,
    filter_player_mentions,
)


class TestFindPlayerMatches:
    """Tests for find_player_matches: the name beside the text that matched it."""

    def test_match_keeps_the_body_spelling(self):
        """The matched text is the body's substring, not the lowercase alias."""
        assert find_player_matches("LEBRON is washed") == [("LeBron James", "LEBRON")]

    def test_short_alias_match_is_the_bounded_word(self):
        """A short alias reports the word the boundary pattern matched."""
        assert find_player_matches("AD had a great game") == [("Anthony Davis", "AD")]

    def test_first_alias_in_config_order_wins(self):
        """Adebayo's aliases are [adebayo, bam], so 'Bam Adebayo' matches as 'Adebayo'."""
        assert find_player_matches("Bam Adebayo is elite") == [
            ("Bam Adebayo", "Adebayo")
        ]

    def test_match_survives_a_length_changing_lowercase(self):
        """'İ' lowercases to two code points; the match still slices the body."""
        assert find_player_matches("İstanbul fans love LeBron") == [
            ("LeBron James", "LeBron")
        ]

    @pytest.mark.parametrize(
        "text",
        [
            "LeBron passed to Curry who missed, KD got the rebound",
            "LeBron to LeBron, he's talking to himself about LeBron",
            "This advertisement is annoying",
            "Steph just hit another 3!",
        ],
    )
    def test_names_agree_with_find_player_mentions(self, text: str):
        """find_player_mentions is the names of find_player_matches, in order."""
        assert [name for name, _ in find_player_matches(text)] == find_player_mentions(
            text
        )

    @pytest.mark.parametrize("text", ["", None, "The game was really exciting"])
    def test_empty_when_nothing_matches(self, text: str | None):
        """Empty, None and mention-free text give an empty list."""
        assert find_player_matches(text) == []


class TestFindPlayerMentions:
    """Tests for find_player_mentions function."""

    def test_finds_player_by_full_name(self):
        """Finds player when full name is mentioned."""
        text = "I think LeBron James is the GOAT"
        result = find_player_mentions(text)

        assert "LeBron James" in result

    def test_finds_player_by_nickname(self):
        """Finds player when nickname is used."""
        text = "Steph just hit another 3!"
        result = find_player_mentions(text)

        assert "Stephen Curry" in result

    def test_case_insensitive_matching(self):
        """Matching is case insensitive."""
        texts = [
            "LEBRON is washed",
            "lebron is washed",
            "LeBrOn is washed",
        ]

        for text in texts:
            result = find_player_mentions(text)
            assert "LeBron James" in result, f"Should match: {text}"

    def test_returns_empty_list_for_no_mentions(self):
        """Returns empty list when no players mentioned."""
        text = "The game was really exciting last night"
        result = find_player_mentions(text)

        assert result == []

    def test_returns_empty_list_for_empty_text(self):
        """Handles empty string gracefully."""
        assert find_player_mentions("") == []

    def test_returns_empty_list_for_none(self):
        """Handles None gracefully."""
        assert find_player_mentions(None) == []

    def test_finds_multiple_players(self):
        """Finds all mentioned players in text."""
        text = "LeBron passed to Curry who missed, KD got the rebound"
        result = find_player_mentions(text)

        assert "LeBron James" in result
        assert "Stephen Curry" in result
        assert "Kevin Durant" in result

    def test_returns_each_player_once(self):
        """Each player appears only once even if mentioned multiple times."""
        text = "LeBron to LeBron, he's talking to himself about LeBron"
        result = find_player_mentions(text)

        assert result.count("LeBron James") == 1


class TestWordBoundaryMatching:
    """Tests for short alias word boundary handling."""

    def test_ad_matches_standalone(self):
        """Short alias 'AD' matches when standalone."""
        text = "AD had a great game"
        result = find_player_mentions(text)

        assert "Anthony Davis" in result

    def test_ad_does_not_match_in_advertisement(self):
        """Short alias 'AD' doesn't match within 'advertisement'."""
        text = "This advertisement is annoying"
        result = find_player_mentions(text)

        assert "Anthony Davis" not in result

    def test_ja_matches_standalone(self):
        """Short alias 'Ja' matches when standalone."""
        text = "Ja is so athletic"
        result = find_player_mentions(text)

        assert "Ja Morant" in result

    def test_ja_does_not_match_in_java(self):
        """Short alias 'Ja' doesn't match within 'java'."""
        text = "I'm coding in java"
        result = find_player_mentions(text)

        assert "Ja Morant" not in result

    def test_curry_matches_standalone(self):
        """Short alias 'Curry' matches when standalone."""
        text = "Curry for three!"
        result = find_player_mentions(text)

        assert "Stephen Curry" in result

    def test_curry_does_not_match_in_currying(self):
        """Short alias 'Curry' doesn't match within 'currying'."""
        text = "I love currying functions in Haskell"
        result = find_player_mentions(text)

        assert "Stephen Curry" not in result

    def test_green_does_not_match_in_greenery(self):
        """Short alias 'Green' doesn't match within 'greenery'."""
        text = "The greenery in this park is beautiful"
        result = find_player_mentions(text)

        assert "Draymond Green" not in result


class TestFilterPlayerMentions:
    """Tests for filter_player_mentions function."""

    def test_returns_none_for_no_mentions(self):
        """Returns None when comment has no player mentions."""
        comment = {"id": "123", "body": "Great game last night"}
        result = filter_player_mentions(comment)

        assert result is None

    def test_returns_comment_with_mentions_field(self):
        """Returns comment with mentioned_players field added."""
        comment = {"id": "123", "body": "LeBron is washed"}
        result = filter_player_mentions(comment)

        assert result is not None
        assert "mentioned_players" in result
        assert "LeBron James" in result["mentioned_players"]

    def test_preserves_original_fields(self):
        """Original comment fields are preserved."""
        comment = {
            "id": "123",
            "body": "LeBron is washed",
            "author": "user1",
            "score": 42,
        }
        result = filter_player_mentions(comment)

        assert result["id"] == "123"
        assert result["body"] == "LeBron is washed"
        assert result["author"] == "user1"
        assert result["score"] == 42

    def test_does_not_mutate_original(self):
        """Original comment dict is not modified."""
        comment = {"id": "123", "body": "LeBron is washed"}
        filter_player_mentions(comment)

        assert "mentioned_players" not in comment

    def test_handles_missing_body(self):
        """Returns None when body field is missing."""
        comment = {"id": "123"}
        result = filter_player_mentions(comment)

        assert result is None

    def test_handles_empty_body(self):
        """Returns None when body is empty string."""
        comment = {"id": "123", "body": ""}
        result = filter_player_mentions(comment)

        assert result is None


class TestFilterPlayerMentionsIntegration:
    """Integration tests for filter_player_mentions with realistic data."""

    def test_accepts_comment_with_player_mention(self):
        """Comment with a player mention is accepted with mentioned_players field."""
        comment = {"id": "123", "body": "LeBron played well"}
        result = filter_player_mentions(comment)

        assert result is not None
        assert "mentioned_players" in result
        assert "LeBron James" in result["mentioned_players"]

    def test_rejects_comment_without_player_mention(self):
        """Comment without player mentions returns None."""
        comment = {"id": "456", "body": "Great game last night"}
        result = filter_player_mentions(comment)

        assert result is None
