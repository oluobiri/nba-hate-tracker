"""
Tests for season-aware data path construction.

Tests verify that path functions return season-scoped directories
and that get_data_dir accepts an explicit season override.
"""

from pathlib import Path

from utils.paths import (
    get_batches_dir,
    get_dashboard_dir,
    get_data_dir,
    get_filtered_dir,
    get_processed_dir,
    get_raw_dir,
)


class TestGetDataDir:
    """Tests for get_data_dir function."""

    def test_returns_path(self):
        """Data dir is a Path object."""
        result = get_data_dir()
        assert isinstance(result, Path)

    def test_includes_active_season(self):
        """Default data dir includes active season from season.yaml."""
        result = get_data_dir()
        assert "2024-25" in str(result)

    def test_explicit_season_override(self):
        """Passing season explicitly overrides the default."""
        result = get_data_dir(season="2025-26")
        assert result.name == "2025-26"

    def test_ends_with_season(self):
        """Data dir ends with the season identifier."""
        result = get_data_dir()
        assert result.name == "2024-25"


class TestLeafPathFunctions:
    """Tests for subdirectory path functions."""

    def test_raw_dir_is_season_scoped(self):
        """Raw dir is under the season directory."""
        result = get_raw_dir()
        assert result.parent.name == "2024-25"
        assert result.name == "raw"

    def test_filtered_dir_is_season_scoped(self):
        """Filtered dir is under the season directory."""
        result = get_filtered_dir()
        assert result.parent.name == "2024-25"
        assert result.name == "filtered"

    def test_batches_dir_is_season_scoped(self):
        """Batches dir is under the season directory."""
        result = get_batches_dir()
        assert result.parent.name == "2024-25"
        assert result.name == "batches"

    def test_processed_dir_is_season_scoped(self):
        """Processed dir is under the season directory."""
        result = get_processed_dir()
        assert result.parent.name == "2024-25"
        assert result.name == "processed"

    def test_dashboard_dir_is_season_scoped(self):
        """Dashboard dir is under the season directory."""
        result = get_dashboard_dir()
        assert result.parent.name == "2024-25"
        assert result.name == "dashboard"
