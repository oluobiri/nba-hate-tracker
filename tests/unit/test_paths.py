"""
Tests for season-aware data path construction.

Tests verify that path functions return season-scoped directories
and that get_data_dir accepts an explicit season override. The active
season is pinned to a synthetic value so tests exercise the plumbing
without depending on the real config/season.yaml.
"""

from pathlib import Path

import pytest

from utils.season_config import get_active_season
from utils.paths import (
    get_batches_dir,
    get_dashboard_dir,
    get_data_dir,
    get_filtered_dir,
    get_processed_dir,
    get_raw_dir,
    get_reference_dir,
)

PINNED_SEASON = "2098-99"


@pytest.fixture
def pinned_season(monkeypatch) -> str:
    """Pin the active season so tests don't depend on config/season.yaml."""
    monkeypatch.setattr("utils.paths.get_active_season", lambda: PINNED_SEASON)
    return PINNED_SEASON


class TestGetDataDir:
    """Tests for get_data_dir function."""

    def test_returns_path(self):
        """Data dir is a Path object."""
        result = get_data_dir()
        assert isinstance(result, Path)

    def test_includes_active_season(self, pinned_season):
        """Default data dir includes the active season."""
        result = get_data_dir()
        assert pinned_season in str(result)

    def test_explicit_season_override(self, pinned_season):
        """Passing season explicitly overrides the active-season default."""
        result = get_data_dir(season="2024-25")
        assert result.name == "2024-25"
        assert pinned_season not in str(result)

    def test_ends_with_season(self, pinned_season):
        """Data dir ends with the season identifier."""
        result = get_data_dir()
        assert result.name == pinned_season

    def test_real_config_wiring_unmocked(self):
        """Smoke test: the real active season from season.yaml lands in the path.

        Deliberately unmocked — the only test exercising the wiring between
        utils.paths and the real config file end-to-end.
        """
        assert get_active_season() in str(get_data_dir())


class TestLeafPathFunctions:
    """Tests for subdirectory path functions."""

    def test_raw_dir_is_season_scoped(self, pinned_season):
        """Raw dir is under the season directory."""
        result = get_raw_dir()
        assert result.parent.name == pinned_season
        assert result.name == "raw"

    def test_filtered_dir_is_season_scoped(self, pinned_season):
        """Filtered dir is under the season directory."""
        result = get_filtered_dir()
        assert result.parent.name == pinned_season
        assert result.name == "filtered"

    def test_batches_dir_is_season_scoped(self, pinned_season):
        """Batches dir is under the season directory."""
        result = get_batches_dir()
        assert result.parent.name == pinned_season
        assert result.name == "batches"

    def test_processed_dir_is_season_scoped(self, pinned_season):
        """Processed dir is under the season directory."""
        result = get_processed_dir()
        assert result.parent.name == pinned_season
        assert result.name == "processed"

    def test_dashboard_dir_is_season_scoped(self, pinned_season):
        """Dashboard dir is under the season directory."""
        result = get_dashboard_dir()
        assert result.parent.name == pinned_season
        assert result.name == "dashboard"

    def test_reference_dir_is_season_scoped(self, pinned_season):
        """Reference dir is under the season directory."""
        result = get_reference_dir()
        assert result.parent.name == pinned_season
        assert result.name == "reference"
