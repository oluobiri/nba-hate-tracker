"""
Tests for the shared quoted-version-string validator.

require_version_string() backs every config loader that stamps lineage
(players.yaml, teams.yaml, season.yaml); its contract is pinned once
here so the per-loader tests only need to check wiring.
"""

from pathlib import Path

import pytest

from utils.config_version import require_version_string


class TestRequireVersionString:
    """Tests for require_version_string function."""

    def test_returns_quoted_string(self):
        """A quoted version passes through unchanged."""
        assert (
            require_version_string({"version": "4.10"}, Path("x.yaml"), "x.yaml")
            == "4.10"
        )

    def test_missing_version_raises_with_label_and_path(self):
        """A config with no version key names the file and its path."""
        with pytest.raises(
            ValueError, match=r"players\.yaml.*'version' key.*cfg/players\.yaml"
        ):
            require_version_string({}, Path("cfg/players.yaml"), "players.yaml")

    def test_unquoted_version_raises(self):
        """A YAML float version (trailing zero lost) is rejected.

        4.10 unquoted parses as the float 4.1 and would silently
        mis-stamp lineage; the message names the offending type.
        """
        with pytest.raises(ValueError, match=r"quoted string.*4\.1.*float"):
            require_version_string({"version": 4.1}, Path("teams.yaml"), "teams.yaml")

    def test_none_config_raises(self):
        """An empty YAML document (parsed as None) reads as no version key."""
        with pytest.raises(ValueError, match="'version' key"):
            require_version_string(None, Path("empty.yaml"), "empty.yaml")
