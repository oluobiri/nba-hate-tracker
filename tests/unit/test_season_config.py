"""
Tests for season configuration loading.

Tests cover loading from YAML, required key validation, convenience
accessors, and caching behavior.
"""

import re

import pytest

from utils.paths import get_data_dir
from utils.player_config import (
    build_alias_to_player_map,
    load_player_config,
    load_player_metadata,
)
from utils.season_config import (
    clear_season_override,
    get_active_season,
    load_season_config,
    set_season_override,
)


def _clear_player_caches() -> None:
    """Clear the season-derived player-config caches."""
    for fn in (load_player_config, build_alias_to_player_map, load_player_metadata):
        fn.cache_clear()


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

    def test_season_and_dates_consistent(self):
        """Season identifier and date range agree, whatever season is active.

        Invariants instead of pinned values so a legitimate season flip
        doesn't break the suite: season is YYYY-YY, start_date falls in
        the first year, end_date in the second.
        """
        config = load_season_config()
        assert re.fullmatch(r"\d{4}-\d{2}", config["season"])
        start_year = int(config["season"][:4])
        assert config["season"][5:7] == str(start_year + 1)[-2:]
        assert config["start_date"].startswith(str(start_year))
        assert config["end_date"].startswith(str(start_year + 1))
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

    def test_matches_season_format(self):
        """Active season is a YYYY-YY identifier."""
        assert re.fullmatch(r"\d{4}-\d{2}", get_active_season())


class TestSeasonOverride:
    """Tests for the process-level --season override (#51)."""

    @pytest.fixture(autouse=True)
    def clean_override_state(self):
        """Cold season-derived caches and no override, before and after."""
        _clear_player_caches()
        clear_season_override()
        yield
        clear_season_override()
        _clear_player_caches()

    def test_override_changes_active_season(self):
        """get_active_season returns the override when set."""
        set_season_override("2024-25")
        assert get_active_season() == "2024-25"

    def test_no_override_uses_config_file(self):
        """Without an override, the on-disk config value is returned."""
        assert get_active_season() == load_season_config()["season"]

    def test_clear_restores_config_value(self):
        """Clearing the override restores the on-disk config value."""
        set_season_override("2024-25")
        clear_season_override()
        assert get_active_season() == load_season_config()["season"]

    def test_override_reaches_paths(self):
        """Path resolution honors the override with no parameter threading."""
        set_season_override("2024-25")
        assert get_data_dir().name == "2024-25"

    def test_override_reaches_player_config(self):
        """The player-config loader resolves the override season's file.

        Pins the 2024-25 config's player count — safe because that
        season is over and its config is frozen.
        """
        set_season_override("2024-25")
        players, _ = load_player_config()
        assert len(players) == 111

    def test_invalid_format_raises(self):
        """A malformed season identifier is rejected up front."""
        with pytest.raises(ValueError, match="YYYY-YY"):
            set_season_override("2024-2025")

    def test_raises_if_caches_already_warm(self):
        """Setting the override after config loading fails loud.

        A silent cache clear could mask early code having already acted
        on the wrong season, so the guard raises instead.
        """
        load_player_config()
        with pytest.raises(RuntimeError, match="script entry"):
            set_season_override("2024-25")
