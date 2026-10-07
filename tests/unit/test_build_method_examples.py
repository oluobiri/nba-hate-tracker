"""Tests for scripts/build_method_examples.py's modes and exit codes."""

from unittest.mock import patch

import polars as pl
import pytest

from pipeline.method_examples import MethodExamplesError
from scripts import build_method_examples


@pytest.fixture
def data_root(monkeypatch, tmp_path, season_override):
    """A tmp data root with the fact present and reference/ empty."""
    season_override("2025-26")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    processed = tmp_path / "2025-26" / "processed"
    processed.mkdir(parents=True)
    (processed / "sentiment.parquet").touch()
    (tmp_path / "2025-26" / "reference").mkdir()
    return tmp_path


def _run(*argv: str):
    with patch.object(
        build_method_examples.sys,
        "argv",
        ["build_method_examples", "--season", "2025-26", *argv],
    ):
        build_method_examples.main()


INPUTS = (pl.DataFrame({"comment_id": ["c1"]}), {}, None, None)


def _report() -> dict[str, pl.DataFrame]:
    return {
        slot: pl.DataFrame(
            {
                "comment_id": ["c1"],
                "mentioned_players": [["LeBron James", "Nikola Jokic"]],
                "score": [10],
                "curation": [f"- {{slot: {slot}, comment_id: c1}}"],
            }
        )
        for slot in ("trace", "case")
    }


class TestMain:
    """Tests for the mode switch and the two modes' side effects."""

    def test_a_mode_is_required(self, data_root):
        """Neither --scan nor --dry-run is a usage error."""
        with pytest.raises(SystemExit) as exit_info:
            _run()
        assert exit_info.value.code == 2

    def test_missing_players_exit_one(self, data_root):
        """Without an aggregate run there is no Player dimension for the ids."""
        with (
            patch.object(
                build_method_examples,
                "load_attributed_frame",
                return_value=(pl.DataFrame(), 0),
            ),
            pytest.raises(SystemExit) as exit_info,
        ):
            _run("--scan")
        assert exit_info.value.code == 1

    def test_scan_writes_one_report_per_slot_and_nothing_else(self, data_root):
        """--scan writes reference/method_example_candidates_<slot>.csv only."""
        counts = pl.DataFrame({"attribution_case": ["one_name"], "rows": [1]})
        with (
            patch.object(build_method_examples, "load_inputs", return_value=INPUTS),
            patch.object(build_method_examples, "attribution_cases", return_value=None),
            patch.object(
                build_method_examples, "count_attribution_cases", return_value=counts
            ),
            patch.object(
                build_method_examples, "scan_candidates", return_value=_report()
            ),
        ):
            _run("--scan")

        reference = data_root / "2025-26" / "reference"
        assert sorted(p.name for p in reference.iterdir()) == [
            "method_example_candidates_case.csv",
            "method_example_candidates_trace.csv",
        ]
        trace = pl.read_csv(reference / "method_example_candidates_trace.csv")
        assert trace["mentioned_players"].to_list() == ["LeBron James | Nikola Jokic"]
        assert trace["curation"].to_list() == ["- {slot: trace, comment_id: c1}"]
        assert not (data_root / "2025-26" / "dashboard").exists()

    def test_dry_run_builds_and_writes_nothing(self, data_root):
        """--dry-run builds the curated table in memory; no file lands."""
        with (
            patch.object(build_method_examples, "load_inputs", return_value=INPUTS),
            patch.object(
                build_method_examples,
                "build_method_examples",
                return_value=pl.DataFrame(
                    {
                        "position": [0],
                        "slot": ["read"],
                        "comment_id": ["c1"],
                        "attribution_case": ["one_name"],
                        "sentiment": ["neg"],
                        "confidence": [0.9],
                        "attributed_player": ["LeBron James"],
                    }
                ),
            ) as build,
        ):
            _run("--dry-run")

        build.assert_called_once()
        assert list((data_root / "2025-26" / "reference").iterdir()) == []
        assert not (data_root / "2025-26" / "dashboard").exists()

    def test_dry_run_with_a_misfit_exits_one(self, data_root):
        """A curated comment that fails its slot is reported, not swallowed."""
        with (
            patch.object(build_method_examples, "load_inputs", return_value=INPUTS),
            patch.object(
                build_method_examples,
                "build_method_examples",
                side_effect=MethodExamplesError(
                    "method_examples trace c1: the slot requires"
                ),
            ),
            pytest.raises(SystemExit) as exit_info,
        ):
            _run("--dry-run")

        assert exit_info.value.code == 1
