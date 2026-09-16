"""
Tests for the config-lineage registry.

The registry is the one place a produced file's config stamps are
declared and spelled; these tests pin that every produced file is
registered and that an unregistered one fails at the write site.
"""

import logging
from pathlib import Path

import pytest

from pipeline.lineage import (
    CONFIG_VERSION_LOADERS,
    OUTPUT_CONFIGS,
    check_config_stamps,
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


class TestCheckConfigStamps:
    """The read-side drift check over a registered output's configs."""

    PATH = Path("data/x/sentiment.parquet")
    LOG = logging.getLogger("tests.lineage")

    def _warnings(self, caplog) -> list[str]:
        return [r.message for r in caplog.records if r.levelno == logging.WARNING]

    def _check(self, metadata: dict, caplog) -> list[str]:
        with caplog.at_level(logging.WARNING, logger="tests.lineage"):
            check_config_stamps(
                self.PATH,
                metadata,
                "sentiment",
                subject="fact",
                remedy="reassemble",
                log=self.LOG,
            )
        return self._warnings(caplog)

    def test_matching_stamps_are_silent(self, caplog):
        """Live versions under the registry keys warn about nothing."""
        assert self._check(config_stamps("sentiment"), caplog) == []

    def test_drift_names_both_versions_and_the_remedy(self, caplog):
        """A stale stamp is reported as drift, with the stamped and live
        versions and the caller's remedy."""
        stamps = {**config_stamps("sentiment"), "teams_config_version": "0.1"}

        warnings = self._check(stamps, caplog)

        assert len(warnings) == 1
        assert "teams_config_version drift" in warnings[0]
        assert "'0.1'" in warnings[0]
        assert repr(CONFIG_VERSION_LOADERS["teams"]()) in warnings[0]
        assert warnings[0].endswith("reassemble")

    def test_absence_is_not_drift(self, caplog):
        """A missing stamp says lineage cannot be verified, not that it drifted."""
        stamps = {"players_config_version": CONFIG_VERSION_LOADERS["players"]()}

        warnings = self._check(stamps, caplog)

        assert len(warnings) == 1
        assert "carries no teams_config_version stamp" in warnings[0]
        assert "drift" not in warnings[0]

    def test_logs_through_the_callers_logger(self, caplog):
        """Warnings carry the calling module's logger name."""
        with caplog.at_level(logging.WARNING, logger="tests.lineage"):
            check_config_stamps(
                self.PATH, {}, "sentiment", subject="fact", remedy="r", log=self.LOG
            )

        assert {r.name for r in caplog.records} == {"tests.lineage"}

    def test_unregistered_output_raises(self):
        """Same registry, same failure: an unknown output has no configs to check."""
        with pytest.raises(KeyError, match="storylines"):
            check_config_stamps(
                self.PATH, {}, "storylines", subject="s", remedy="r", log=self.LOG
            )
