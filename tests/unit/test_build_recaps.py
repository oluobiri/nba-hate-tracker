"""Tests for scripts/build_recaps.py's modes and exit codes."""

from unittest.mock import patch

import polars as pl
import pytest

from scripts import build_recaps


@pytest.fixture
def data_root(monkeypatch, tmp_path, season_override):
    """A tmp data root with the fact present and the dashboard tables stubbed.

    main() sets a process-level season override; the season_override
    fixture's teardown clears it so later tests see the on-disk season.
    """
    season_override("2025-26")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    processed = tmp_path / "2025-26" / "processed"
    processed.mkdir(parents=True)
    (processed / "sentiment.parquet").touch()
    (tmp_path / "2025-26" / "reference").mkdir()
    return tmp_path


def _run(*argv: str):
    with patch.object(
        build_recaps.sys, "argv", ["build_recaps", "--season", "2025-26", *argv]
    ):
        build_recaps.main()


TABLES = {
    **{name: pl.DataFrame({"x": [1]}) for name in build_recaps.TABLES},
    "posts": pl.DataFrame({"post_id": ["t3_live"], "post_type": ["game_thread"]}),
}


class TestMain:
    """Tests for the mode switch and the two modes' side effects."""

    def test_a_mode_is_required(self, data_root):
        """Neither --scan nor --dry-run is a usage error."""
        with pytest.raises(SystemExit) as exit_info:
            _run()
        assert exit_info.value.code == 2

    def test_missing_tables_exit_one(self, data_root):
        """Without an aggregate run there is nothing to resolve against."""
        with pytest.raises(SystemExit) as exit_info:
            _run("--dry-run")
        assert exit_info.value.code == 1

    def test_scan_writes_the_report_and_nothing_else(self, data_root):
        """--scan writes reference/recap_candidates.csv only."""
        candidates = pl.DataFrame(
            {
                "game_id": ["0042500317"],
                "attributed_player": ["Chet Holmgren"],
                "live_n": [2069],
                "swing": [-0.4],
            }
        )
        with (
            patch.object(build_recaps, "load_tables", return_value=TABLES),
            patch.object(build_recaps, "load_fact_subset", return_value=pl.DataFrame()),
            patch.object(
                build_recaps, "scan_candidates", return_value=(candidates, [])
            ),
        ):
            _run("--scan")

        out = data_root / "2025-26" / "reference" / "recap_candidates.csv"
        assert out.exists()
        assert pl.read_csv(out)["game_id"].to_list() == [42500317]
        assert not (data_root / "2025-26" / "dashboard" / "recaps").exists()

    def test_dry_run_builds_and_writes_nothing(self, data_root):
        """--dry-run builds each resolved recap in memory; no file lands."""
        with (
            patch.object(build_recaps, "load_tables", return_value=TABLES),
            patch.object(build_recaps, "resolve_recap_specs", return_value=[]),
            patch.object(build_recaps, "load_fact_subset", return_value=pl.DataFrame()),
            patch.object(build_recaps, "read_classifier_stamps", return_value={}),
            patch.object(build_recaps, "build_recap") as build,
        ):
            _run("--dry-run")

        build.assert_not_called()
        assert not (data_root / "2025-26" / "dashboard").exists()
