"""
Tests for player configuration loading.

Tests cover loading from YAML, alias map building, and caching behavior.
"""

from utils.player_config import (
    build_alias_to_player_map,
    load_player_config,
    load_player_metadata,
)


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


class TestBuildAliasToPlayerMap:
    """Tests for build_alias_to_player_map function."""

    def test_returns_dict(self):
        """Alias map is a dict."""
        alias_map = build_alias_to_player_map()
        assert isinstance(alias_map, dict)

    def test_known_alias_resolves_to_canonical(self):
        """A known alias maps to its canonical player name."""
        alias_map = build_alias_to_player_map()
        assert alias_map["jokic"] == "Nikola Jokic"

    def test_canonical_name_lowercased_resolves(self):
        """Canonical name itself (lowercased) resolves correctly."""
        alias_map = build_alias_to_player_map()
        assert alias_map["nikola jokic"] == "Nikola Jokic"

    def test_lebron_alias_resolves(self):
        """LeBron alias resolves to canonical name."""
        alias_map = build_alias_to_player_map()
        assert alias_map["lebron"] == "LeBron James"
        assert alias_map["lbj"] == "LeBron James"

    def test_caching_returns_same_object(self):
        """Multiple calls return the same cached object."""
        result1 = build_alias_to_player_map()
        result2 = build_alias_to_player_map()
        assert result1 is result2


class TestLoadPlayerMetadata:
    """Tests for load_player_metadata function."""

    def test_returns_dict(self):
        """Metadata loader returns a dict."""
        metadata = load_player_metadata()
        assert isinstance(metadata, dict)

    def test_metadata_has_required_fields(self):
        """Each player has team, conference, player_id, headshot_url."""
        metadata = load_player_metadata()

        for player_name, player_meta in metadata.items():
            assert isinstance(player_name, str)
            assert isinstance(player_meta, dict)
            assert "team" in player_meta, f"{player_name} missing 'team'"
            assert "conference" in player_meta, f"{player_name} missing 'conference'"
            assert "player_id" in player_meta, f"{player_name} missing 'player_id'"
            assert "headshot_url" in player_meta, f"{player_name} missing 'headshot_url'"

    def test_conference_values_valid(self):
        """Conference is always 'East' or 'West'."""
        metadata = load_player_metadata()

        for player_name, player_meta in metadata.items():
            assert player_meta["conference"] in {"East", "West"}, (
                f"{player_name} has invalid conference: {player_meta['conference']}"
            )

    def test_lebron_metadata(self):
        """LeBron James has correct metadata."""
        metadata = load_player_metadata()

        assert "LeBron James" in metadata
        lebron = metadata["LeBron James"]

        assert lebron["team"] == "Los Angeles Lakers"
        assert lebron["conference"] == "West"
        assert lebron["player_id"] == 2544

    def test_caching_returns_same_object(self):
        """Multiple calls return the same cached object."""
        result1 = load_player_metadata()
        result2 = load_player_metadata()
        assert result1 is result2

    def test_metadata_count_matches_players(self):
        """Metadata count matches player count from load_player_config."""
        players, _ = load_player_config()
        metadata = load_player_metadata()
        assert len(metadata) == len(players)
