"""
Tests for season configuration loading.

Tests cover loading from YAML, required key validation, convenience
accessors, and caching behavior.
"""

from utils.season_config import get_active_season, load_season_config


class TestLoadSeasonConfig:
    """Tests for load_season_config function."""

    def test_returns_dict(self):
        """Config loader returns a dict."""
        config = load_season_config()
        assert isinstance(config, dict)

    def test_has_required_keys(self):
        """Config contains all required keys."""
        config = load_season_config()
        assert "season" in config
        assert "start_date" in config
        assert "end_date" in config
        assert "subreddits" in config

    def test_season_is_string(self):
        """Season identifier is a string."""
        config = load_season_config()
        assert isinstance(config["season"], str)

    def test_dates_are_iso_format(self):
        """Start and end dates are valid ISO date strings."""
        config = load_season_config()
        for key in ("start_date", "end_date"):
            parts = config[key].split("-")
            assert len(parts) == 3, f"{key} should be YYYY-MM-DD"
            assert len(parts[0]) == 4, f"{key} year should be 4 digits"

    def test_subreddits_is_nonempty_tuple(self):
        """Subreddits is a non-empty tuple of strings (frozen for cache safety)."""
        config = load_season_config()
        subreddits = config["subreddits"]
        assert isinstance(subreddits, tuple)
        assert len(subreddits) > 0
        for sub in subreddits:
            assert isinstance(sub, str)

    def test_current_season_values(self):
        """Current config has expected 2024-25 values."""
        config = load_season_config()
        assert config["season"] == "2024-25"
        assert config["start_date"] == "2024-10-01"
        assert config["end_date"] == "2025-06-30"
        assert "nba" in config["subreddits"]

    def test_caching_returns_same_object(self):
        """Multiple calls return the same cached object."""
        result1 = load_season_config()
        result2 = load_season_config()
        assert result1 is result2


class TestGetActiveSeason:
    """Tests for get_active_season convenience function."""

    def test_returns_string(self):
        """Active season is a string."""
        season = get_active_season()
        assert isinstance(season, str)

    def test_matches_config(self):
        """Active season matches what load_season_config returns."""
        config = load_season_config()
        assert get_active_season() == config["season"]

    def test_current_value(self):
        """Active season is currently 2024-25."""
        assert get_active_season() == "2024-25"
