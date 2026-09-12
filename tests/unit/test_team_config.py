"""
Tests for team configuration loading.

Tests cover loading from YAML, alias map building, version loading,
caching behavior, and flair resolution.
"""

import re

import pytest

from utils.team_config import (
    build_alias_to_team_map,
    extract_team_from_flair,
    load_team_config,
    load_team_config_version,
)


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
            assert isinstance(info["conference"], str), f"{team_name} missing conference"
            assert isinstance(info["team_id"], int), f"{team_name} missing team_id"
            assert isinstance(info["logo_url"], str), f"{team_name} missing logo_url"
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


class TestLoadTeamConfigVersion:
    """Tests for load_team_config_version function."""

    @pytest.fixture
    def cold_version_cache(self):
        """Clear the version loader's cache before and after the test.

        The invalid-config tests monkeypatch the config path; a warm
        cache would return the real config's version and never consult
        the patched path.
        """
        load_team_config_version.cache_clear()
        yield
        load_team_config_version.cache_clear()

    def test_returns_version_string(self):
        """Version is a MAJOR.MINOR string (format pinned, not the value —
        the version bumps on team-config changes)."""
        version = load_team_config_version()
        assert re.fullmatch(r"\d+\.\d+", version)

    def test_caching_returns_same_object(self):
        """Multiple calls return the same cached object."""
        result1 = load_team_config_version()
        result2 = load_team_config_version()
        assert result1 is result2

    def test_missing_version_raises(self, tmp_path, monkeypatch, cold_version_cache):
        """A teams.yaml without a version key raises ValueError with context."""
        config_path = tmp_path / "teams.yaml"
        config_path.write_text("teams: {}\n")
        monkeypatch.setattr("utils.team_config.CONFIG_PATH", config_path)

        with pytest.raises(ValueError, match="version"):
            load_team_config_version()

    def test_unquoted_version_raises(self, tmp_path, monkeypatch, cold_version_cache):
        """An unquoted YAML version (parsed as float) raises ValueError.

        Floats silently lose trailing zeros (2.10 -> "2.1"), which would
        mis-stamp lineage; the loader demands a quoted string instead.
        """
        config_path = tmp_path / "teams.yaml"
        config_path.write_text("version: 2.10\nteams: {}\n")
        monkeypatch.setattr("utils.team_config.CONFIG_PATH", config_path)

        with pytest.raises(ValueError, match="quoted string"):
            load_team_config_version()


class TestExtractTeamFromFlair:
    """Tests for extract_team_from_flair function."""

    def test_standard_flair(self, team_alias_map):
        """Standard Reddit flair with emoji prefix resolves."""
        result = extract_team_from_flair(":lal-1: Lakers", team_alias_map)
        assert result == "Los Angeles Lakers"

    def test_abbreviation_flair(self, team_alias_map):
        """Abbreviation-only flair resolves."""
        result = extract_team_from_flair(":bos-1:", team_alias_map)
        assert result == "Boston Celtics"

    def test_plain_text_flair(self, team_alias_map):
        """Plain text team name resolves."""
        result = extract_team_from_flair("Celtics", team_alias_map)
        assert result == "Boston Celtics"

    def test_null_flair(self, team_alias_map):
        """Null flair returns None."""
        result = extract_team_from_flair(None, team_alias_map)
        assert result is None

    def test_empty_flair(self, team_alias_map):
        """Empty string flair returns None."""
        result = extract_team_from_flair("", team_alias_map)
        assert result is None

    def test_unrecognized_flair(self, team_alias_map):
        """Unrecognized flair text returns None."""
        result = extract_team_from_flair(":AUS: Australia", team_alias_map)
        assert result is None

    def test_legacy_code_flair(self, team_alias_map):
        """Legacy Reddit flair code resolves."""
        result = extract_team_from_flair(":njn-1:", team_alias_map)
        assert result == "Brooklyn Nets"

    def test_substring_collision_hornets_not_nets(self, team_alias_map):
        """Hornets flair matches Charlotte, not Brooklyn (nets substring)."""
        result = extract_team_from_flair(":cha-1: Hornets", team_alias_map)
        assert result == "Charlotte Hornets"
