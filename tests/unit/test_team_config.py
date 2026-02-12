"""
Tests for team configuration loading.

Tests cover loading from YAML, alias map building, and caching behavior.
"""

from utils.team_config import build_alias_to_team_map, load_team_config


class TestLoadTeamConfig:
    """Tests for load_team_config function."""

    def test_returns_dict(self):
        """Config loader returns a dict."""
        teams = load_team_config()
        assert isinstance(teams, dict)

    def test_contains_30_teams(self):
        """Config contains exactly 30 NBA teams."""
        teams = load_team_config()
        assert len(teams) == 30

    def test_each_team_has_required_fields(self):
        """Each team has abbreviation (str) and aliases (list)."""
        teams = load_team_config()
        for team_name, info in teams.items():
            assert isinstance(info["abbreviation"], str), f"{team_name} missing abbreviation"
            assert isinstance(info["aliases"], list), f"{team_name} missing aliases"

    def test_lakers_exists_with_abbreviation(self):
        """Los Angeles Lakers exists with correct abbreviation."""
        teams = load_team_config()
        assert "Los Angeles Lakers" in teams
        assert teams["Los Angeles Lakers"]["abbreviation"] == "LAL"

    def test_caching_returns_same_object(self):
        """Multiple calls return the same cached object."""
        result1 = load_team_config()
        result2 = load_team_config()
        assert result1 is result2


class TestBuildAliasToTeamMap:
    """Tests for build_alias_to_team_map function."""

    def test_returns_dict(self):
        """Alias map is a dict."""
        alias_map = build_alias_to_team_map()
        assert isinstance(alias_map, dict)

    def test_known_alias_resolves(self):
        """A known alias maps to its canonical team name."""
        alias_map = build_alias_to_team_map()
        assert alias_map["lal"] == "Los Angeles Lakers"
        assert alias_map["lakers"] == "Los Angeles Lakers"

    def test_legacy_code_resolves(self):
        """Legacy Reddit flair codes resolve correctly."""
        alias_map = build_alias_to_team_map()
        assert alias_map["njn"] == "Brooklyn Nets"

    def test_team_name_lowercased_resolves(self):
        """Team name itself (lowercased) resolves correctly."""
        alias_map = build_alias_to_team_map()
        assert alias_map["boston celtics"] == "Boston Celtics"

    def test_abbreviation_resolves(self):
        """Official abbreviation resolves correctly."""
        alias_map = build_alias_to_team_map()
        assert alias_map["bos"] == "Boston Celtics"

    def test_caching_returns_same_object(self):
        """Multiple calls return the same cached object."""
        result1 = build_alias_to_team_map()
        result2 = build_alias_to_team_map()
        assert result1 is result2
