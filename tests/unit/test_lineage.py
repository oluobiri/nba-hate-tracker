"""
Tests for the config-lineage registry.

The registry is the one place a produced file's config stamps are
declared and spelled; these tests pin that every produced file is
registered and that an unregistered one fails at the write site.
"""

import pytest

from pipeline.lineage import (
    CONFIG_VERSION_LOADERS,
    OUTPUT_CONFIGS,
    config_stamp_key,
    config_stamps,
    config_versions,
)
from pipeline.schemas import DASHBOARD_OUTPUT_SCHEMAS
from utils.player_config import load_player_config_version
from utils.season_config import load_season_config_version
from utils.team_config import load_team_config_version


class TestConfigVersionLoaders:
    """The config name -> version-loader registry."""

    def test_registers_every_versioned_config(self):
        """players, teams and season are the three versioned configs."""
        assert CONFIG_VERSION_LOADERS == {
            "players": load_player_config_version,
            "teams": load_team_config_version,
            "season": load_season_config_version,
        }

    def test_config_versions_reads_every_loader(self):
        """config_versions() is the live version of every registered config."""
        versions = config_versions()

        assert set(versions) == set(CONFIG_VERSION_LOADERS)
        for name, load in CONFIG_VERSION_LOADERS.items():
            assert versions[name] == load()
            assert isinstance(versions[name], str)


class TestConfigStampKey:
    """The parquet metadata key a config's version is stamped under."""

    @pytest.mark.parametrize("config", ["players", "teams", "season"])
    def test_spells_the_stamp_key(self, config):
        """<config>_config_version, the key every write and read site uses."""
        assert config_stamp_key(config) == f"{config}_config_version"

    def test_unknown_config_raises(self):
        """A config that has no version loader has no stamp key either."""
        with pytest.raises(KeyError, match="storylines"):
            config_stamp_key("storylines")


class TestOutputConfigs:
    """Which configs each produced file derives from."""

    def test_every_dashboard_output_is_registered(self):
        """A produced table missing from the registry can't be stamped, so
        the registry must enumerate DASHBOARD_OUTPUT_SCHEMAS in full."""
        assert set(DASHBOARD_OUTPUT_SCHEMAS) <= set(OUTPUT_CONFIGS)

    def test_the_fact_is_registered(self):
        """sentiment.parquet derives its attribution and fan_team from both configs."""
        assert OUTPUT_CONFIGS["sentiment"] == ("players", "teams")

    def test_dimensions_carry_their_config(self):
        """The Player and Team dimensions are exports of their configs."""
        assert OUTPUT_CONFIGS["players"] == ("players",)
        assert OUTPUT_CONFIGS["teams"] == ("teams",)

    def test_declared_configs_have_loaders(self):
        """Every config an output declares is a registered, loadable config."""
        for output, configs in OUTPUT_CONFIGS.items():
            for config in configs:
                assert config in CONFIG_VERSION_LOADERS, (output, config)


class TestConfigStamps:
    """The live stamps for one produced file."""

    def test_dimension_stamps_are_the_live_versions(self):
        """players.parquet carries players_config_version at the live value."""
        assert config_stamps("players") == {
            "players_config_version": load_player_config_version()
        }

    def test_config_free_output_has_no_stamps(self):
        """A fact rollup derives from no config directly: empty, not missing."""
        assert config_stamps("player_overall") == {}

    def test_unregistered_output_raises(self):
        """An output that isn't registered fails loudly at the write site
        instead of shipping unstamped."""
        with pytest.raises(KeyError, match="storylines"):
            config_stamps("storylines")
