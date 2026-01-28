"""
Tests for player configuration loading.

Tests cover loading from YAML, caching behavior, and data structure validation.
"""

from utils.player_config import load_player_config


class TestLoadPlayerConfig:
    """Tests for load_player_config function."""

    def test_returns_tuple_of_dict_and_frozenset(self):
        """Config loader returns correct data types."""
        players, short_aliases = load_player_config()

        assert isinstance(players, dict)
        assert isinstance(short_aliases, frozenset)

    def test_players_dict_has_aliases(self):
        """Each player in config has a list of aliases."""
        players, _ = load_player_config()

        for player_name, aliases in players.items():
            assert isinstance(player_name, str)
            assert isinstance(aliases, list)
            assert len(aliases) > 0, f"{player_name} should have at least one alias"

    def test_lebron_exists_with_expected_aliases(self):
        """LeBron James exists and has key aliases."""
        players, _ = load_player_config()

        assert "LeBron James" in players
        lebron_aliases = players["LeBron James"]

        # Check for some expected aliases
        assert "lebron" in lebron_aliases
        assert "bron" in lebron_aliases
        assert "lbj" in lebron_aliases

    def test_short_aliases_are_lowercase(self):
        """All short aliases are stored in lowercase."""
        _, short_aliases = load_player_config()

        for alias in short_aliases:
            assert alias == alias.lower(), f"Short alias '{alias}' should be lowercase"

    def test_short_aliases_contains_expected_entries(self):
        """Short aliases includes known entries requiring word boundaries."""
        _, short_aliases = load_player_config()

        # These require word boundary matching
        expected = {"ad", "curry", "james", "green", "ja"}
        assert expected.issubset(short_aliases)

    def test_caching_returns_same_object(self):
        """Multiple calls return the same cached object."""
        result1 = load_player_config()
        result2 = load_player_config()

        # Same tuple object (not just equal values)
        assert result1 is result2

    def test_players_count_reasonable(self):
        """Config has a reasonable number of players (sanity check)."""
        players, _ = load_player_config()

        # Should have dozens of players, but not thousands
        assert 30 < len(players) < 200
