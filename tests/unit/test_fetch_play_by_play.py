"""Tests for scripts/fetch_play_by_play.py's run outcome."""

from unittest.mock import patch

import pytest

from pipeline.nba_stats import PlayByPlayMiss, PlayByPlayReport
from scripts import fetch_play_by_play

GAME_IDS = ["0042500317", "0042500405"]


@pytest.fixture
def run_main(monkeypatch, tmp_path, season_override):
    """Run main() against a tmp data root with the game list and sync stubbed.

    main() sets a process-level season override; the season_override
    fixture's teardown clears it so later tests see the on-disk season.
    """
    season_override("2025-26")

    def _run(report: PlayByPlayReport, *argv: str):
        return _main(monkeypatch, tmp_path, report, *argv)

    return _run


def _main(monkeypatch, tmp_path, report: PlayByPlayReport, *argv: str):
    """Invoke main() with --season 2025-26 and the given extra argv."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.argv", ["fetch_play_by_play", "--season", "2025-26", *argv]
    )
    (tmp_path / "2025-26" / "reference").mkdir(parents=True)
    (tmp_path / "2025-26" / "reference" / "team_game_log.parquet").touch()
    with (
        patch.object(fetch_play_by_play, "load_game_ids", return_value=GAME_IDS),
        patch.object(
            fetch_play_by_play, "sync_play_by_play", return_value=report
        ) as sync,
    ):
        fetch_play_by_play.main()
    return sync


class TestMain:
    """Tests for the exit code and the dry run."""

    def test_misses_exit_non_zero(self, run_main):
        """Any miss makes the run exit 1."""
        report = PlayByPlayReport(
            fetched=[GAME_IDS[1]],
            skipped=[],
            misses=[
                PlayByPlayMiss(game_id=GAME_IDS[0], reason="ValueError: zero actions")
            ],
        )
        with pytest.raises(SystemExit) as exit_info:
            run_main(report)
        assert exit_info.value.code == 1

    def test_clean_run_returns(self, run_main):
        """A run without misses exits normally and syncs the full game list."""
        report = PlayByPlayReport(fetched=GAME_IDS, skipped=[], misses=[])
        sync = run_main(report)
        assert sync.call_args.args[0] == GAME_IDS

    def test_dry_run_makes_no_request(self, run_main):
        """--dry-run plans only; the sync never runs."""
        report = PlayByPlayReport(fetched=[], skipped=[], misses=[])
        sync = run_main(report, "--dry-run")
        sync.assert_not_called()
