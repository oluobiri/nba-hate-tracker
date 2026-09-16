"""
Tests for the corpus at day grain (pipeline/corpus.py).

Cover the UTC day bucketing, the zero-filled grid over the download's
extent, the one-owner totals check, and the snapshot loader's
degrade-and-assert behavior.
"""

import json
import logging
from datetime import date

import polars as pl
import pytest

from pipeline.corpus import (
    CORPUS_DAILY_FILENAME,
    build_corpus_daily,
    check_corpus_totals,
    count_by_day,
    count_fact_by_day,
    count_ndjson_by_day,
    load_corpus_daily,
)
from pipeline.schemas import CORPUS_DAILY_SCHEMA, SENTIMENT_SCHEMA
from utils.season_config import get_active_season

# 2024-01-01T00:00:00Z and the second before it: two UTC days.
MIDNIGHT = 1704067200
BEFORE_MIDNIGHT = MIDNIGHT - 1


def _epochs(*values: int) -> pl.DataFrame:
    return pl.DataFrame({"created_utc": list(values)}, schema={"created_utc": pl.Int64})


def _counts(name: str, rows: dict[date, int]) -> pl.DataFrame:
    return pl.DataFrame(
        {"day": list(rows), name: list(rows.values())},
        schema={"day": pl.Date, name: pl.Int64},
    )


class TestCountByDay:
    """Tests for count_by_day (UTC bucketing)."""

    def test_buckets_on_the_utc_day(self):
        """A second before UTC midnight and midnight itself are two days,
        whatever the session timezone."""
        counts = count_by_day(_epochs(BEFORE_MIDNIGHT, MIDNIGHT, MIDNIGHT), "n")

        assert counts.to_dicts() == [
            {"day": date(2023, 12, 31), "n": 1},
            {"day": date(2024, 1, 1), "n": 2},
        ]

    def test_count_is_int64(self):
        """The count is Int64, never the UInt32 of pl.len()."""
        counts = count_by_day(_epochs(MIDNIGHT), "n")

        assert counts.schema == pl.Schema({"day": pl.Date, "n": pl.Int64})

    def test_missing_created_utc_raises(self):
        """A row with no created_utc fails loudly rather than vanishing from the sums."""
        epochs = pl.DataFrame(
            {"created_utc": [MIDNIGHT, None]}, schema={"created_utc": pl.Int64}
        )

        with pytest.raises(ValueError, match="1 row\\(s\\) carry no created_utc"):
            count_by_day(epochs, "n")


class TestCountSources:
    """Tests for the two source counters (NDJSON download, fact parquet)."""

    def test_ndjson_projects_created_utc_only(self, tmp_path):
        """A download line carries many fields; only created_utc is read."""
        path = tmp_path / "r_nba_comments.jsonl"
        with open(path, "w") as f:
            for epoch in (BEFORE_MIDNIGHT, MIDNIGHT, MIDNIGHT):
                f.write(json.dumps({"id": "x", "body": "hi", "created_utc": epoch}))
                f.write("\n")

        counts = count_ndjson_by_day(path, "raw_comments")

        assert counts["raw_comments"].to_list() == [1, 2]

    def test_ndjson_path_with_quote_and_space(self, tmp_path):
        """The path is passed to DuckDB as a value, never spliced into SQL."""
        directory = tmp_path / "o'brien drive"
        directory.mkdir()
        path = directory / "r_nba_comments.jsonl"
        path.write_text(json.dumps({"created_utc": MIDNIGHT}) + "\n")

        counts = count_ndjson_by_day(path, "raw_comments")

        assert counts["raw_comments"].to_list() == [1]

    def test_fact_counts_usable_and_attributed(self, tmp_path):
        """usable excludes error rows; attributed needs an attributed_player."""
        rows = {
            "comment_id": ["c1", "c2", "c3", "c4"],
            "body": ["a", "b", "c", "d"],
            "author": ["u"] * 4,
            "author_flair_text": [None] * 4,
            "author_flair_css_class": [None] * 4,
            "created_utc": [MIDNIGHT, MIDNIGHT, MIDNIGHT, MIDNIGHT + 86400],
            "score": [1] * 4,
            "link_id": ["t3_p"] * 4,
            "mentioned_players": [["LeBron James"]] * 4,
            "sentiment": ["neg", "error", "pos", "neu"],
            "confidence": [0.9] * 4,
            "sentiment_player": ["LeBron James"] * 4,
            "attributed_player": ["LeBron James", "LeBron James", None, "LeBron James"],
            "fan_team": [None] * 4,
            "input_tokens": [1] * 4,
            "output_tokens": [1] * 4,
        }
        path = tmp_path / "sentiment.parquet"
        pl.DataFrame(rows, schema=SENTIMENT_SCHEMA).write_parquet(path)

        counts = count_fact_by_day(path)

        assert counts.to_dicts() == [
            {"day": date(2024, 1, 1), "usable": 2, "attributed": 1},
            {"day": date(2024, 1, 2), "usable": 1, "attributed": 1},
        ]


class TestCountFactWithoutAttribution:
    """A fact assembled before attribution was materialized."""

    def test_leaves_attributed_out_and_warns(self, tmp_path, caplog):
        """usable is counted; attributed is absent, not zero."""
        rows = {
            "comment_id": ["c1", "c2"],
            "body": ["a", "b"],
            "author": ["u", "u"],
            "author_flair_text": [None, None],
            "author_flair_css_class": [None, None],
            "created_utc": [MIDNIGHT, MIDNIGHT],
            "score": [1, 1],
            "link_id": ["t3_p", "t3_p"],
            "mentioned_players": [["LeBron James"], ["LeBron James"]],
            "sentiment": ["neg", "error"],
            "confidence": [0.9, 0.9],
            "sentiment_player": ["LeBron James", "LeBron James"],
            "input_tokens": [1, 1],
            "output_tokens": [1, 1],
        }
        path = tmp_path / "sentiment.parquet"
        pl.DataFrame(rows).write_parquet(path)

        with caplog.at_level(logging.WARNING, logger="pipeline.corpus"):
            counts = count_fact_by_day(path)

        assert counts.to_dicts() == [{"day": date(2024, 1, 1), "usable": 1}]
        assert "attributed is null until" in caplog.text


class TestBuildCorpusDaily:
    """Tests for build_corpus_daily (the zero-filled grid)."""

    def test_present_but_empty_stage_zero_fills(self):
        """An attributed count that exists with no rows is zero, not null:
        only an absent column is unknown."""
        raw = _counts("raw_comments", {date(2024, 1, 1): 5})
        submitted = _counts("population_submitted", {date(2024, 1, 1): 3})
        fact = pl.DataFrame(
            {"day": [date(2024, 1, 1)], "usable": [2], "attributed": [None]},
            schema={"day": pl.Date, "usable": pl.Int64, "attributed": pl.Int64},
        )

        table = build_corpus_daily(raw, submitted, fact)

        assert table["attributed"].to_list() == [0]

    def test_unknown_stage_is_null_not_zero(self):
        """Without an attributed count the column is null on every day,
        while the counted stages still zero-fill."""
        raw = _counts("raw_comments", {date(2024, 1, 1): 5, date(2024, 1, 2): 1})
        submitted = _counts("population_submitted", {date(2024, 1, 1): 3})
        fact = _counts("usable", {date(2024, 1, 1): 2})

        table = build_corpus_daily(raw, submitted, fact)

        assert table.schema == CORPUS_DAILY_SCHEMA
        assert table["attributed"].null_count() == 2
        assert table["population_submitted"].to_list() == [3, 0]

    def test_conforms_and_zero_fills_the_gap(self):
        """A day with raw rows but nothing downstream shows zeros; a day in
        the extent with nothing anywhere is a zero row, not a missing one."""
        raw = _counts("raw_comments", {date(2024, 1, 1): 5, date(2024, 1, 3): 2})
        submitted = _counts("population_submitted", {date(2024, 1, 1): 3})
        fact = pl.DataFrame(
            {"day": [date(2024, 1, 1)], "usable": [2], "attributed": [1]},
            schema={"day": pl.Date, "usable": pl.Int64, "attributed": pl.Int64},
        )

        table = build_corpus_daily(raw, submitted, fact)

        assert table.schema == CORPUS_DAILY_SCHEMA
        assert table.to_dicts() == [
            {
                "day": date(2024, 1, 1),
                "raw_comments": 5,
                "population_submitted": 3,
                "usable": 2,
                "attributed": 1,
            },
            {
                "day": date(2024, 1, 2),
                "raw_comments": 0,
                "population_submitted": 0,
                "usable": 0,
                "attributed": 0,
            },
            {
                "day": date(2024, 1, 3),
                "raw_comments": 2,
                "population_submitted": 0,
                "usable": 0,
                "attributed": 0,
            },
        ]

    def test_extent_spans_every_source(self):
        """The grid runs from the earliest to the latest day of any source."""
        raw = _counts("raw_comments", {date(2024, 1, 2): 1})
        submitted = _counts("population_submitted", {date(2024, 1, 1): 1})
        fact = pl.DataFrame(
            {"day": [date(2024, 1, 4)], "usable": [1], "attributed": [0]},
            schema={"day": pl.Date, "usable": pl.Int64, "attributed": pl.Int64},
        )

        table = build_corpus_daily(raw, submitted, fact)

        assert table["day"].to_list() == [date(2024, 1, d) for d in (1, 2, 3, 4)]

    def test_empty_sources_raise(self):
        """No days anywhere is a build error, not an empty table."""
        empty = _counts("raw_comments", {})
        fact = pl.DataFrame(
            schema={"day": pl.Date, "usable": pl.Int64, "attributed": pl.Int64}
        )

        with pytest.raises(ValueError, match="no days"):
            build_corpus_daily(empty, _counts("population_submitted", {}), fact)


def _table(raw: int, submitted: int) -> pl.DataFrame:
    """A one-row corpus_daily with the given owned totals."""
    return pl.DataFrame(
        {
            "day": [date(2024, 1, 1)],
            "raw_comments": [raw],
            "population_submitted": [submitted],
            "usable": [1],
            "attributed": [1],
        },
        schema=CORPUS_DAILY_SCHEMA,
    )


class TestCheckCorpusTotals:
    """Tests for check_corpus_totals (the corpus numbers' one owner)."""

    def test_matching_totals_pass(self):
        """Sums equal to the record are silent."""
        check_corpus_totals(
            _table(10, 4), {"raw_comments": 10, "population_submitted": 4}
        )

    def test_mismatch_raises_naming_both_figures(self):
        """A sum that disagrees with the record fails, naming column, sum, record."""
        with pytest.raises(
            ValueError, match="population_submitted sums to 4 .* records 5"
        ):
            check_corpus_totals(
                _table(10, 4), {"raw_comments": 10, "population_submitted": 5}
            )

    def test_unrecorded_figure_warns_and_skips(self, caplog):
        """A null record can't be verified; the build proceeds with a warning."""
        with caplog.at_level(logging.WARNING, logger="pipeline.corpus"):
            check_corpus_totals(
                _table(10, 4), {"raw_comments": None, "population_submitted": 4}
            )

        assert "raw_comments is unrecorded" in caplog.text


class TestLoadCorpusDaily:
    """Tests for load_corpus_daily (the snapshot's passage to export)."""

    FACTS = {"raw_comments": 10, "population_submitted": 4}

    def _write(self, ref_dir, table=None, *, season=None):
        (table if table is not None else _table(10, 4)).write_parquet(
            ref_dir / CORPUS_DAILY_FILENAME,
            metadata={
                "season": season or get_active_season(),
                "processed_at": "2026-09-16",
            },
        )

    def test_missing_snapshot_degrades_to_empty(self, tmp_path, caplog):
        """Aggregation stays runnable before the table has been built."""
        with caplog.at_level(logging.WARNING, logger="pipeline.corpus"):
            table, metadata = load_corpus_daily(tmp_path, self.FACTS)

        assert table.schema == CORPUS_DAILY_SCHEMA
        assert table.height == 0
        assert metadata == {"corpus_daily_processed_at": None}
        assert "scripts.build_corpus_daily" in caplog.text

    def test_present_snapshot_is_exported_with_its_stamp(self, tmp_path):
        """The table ships as cached, its build date carried forward."""
        self._write(tmp_path)

        table, metadata = load_corpus_daily(tmp_path, self.FACTS)

        assert table.equals(_table(10, 4))
        assert metadata == {"corpus_daily_processed_at": "2026-09-16"}

    def test_totals_mismatch_fails_the_export(self, tmp_path):
        """A snapshot that disagrees with season.yaml never ships."""
        self._write(tmp_path, _table(11, 4))

        with pytest.raises(ValueError, match="raw_comments sums to 11"):
            load_corpus_daily(tmp_path, self.FACTS)

    def test_other_seasons_snapshot_warns(self, tmp_path, caplog):
        """A snapshot built for another season is read, not silently."""
        self._write(tmp_path, season="1999-00")

        with caplog.at_level(logging.WARNING, logger="pipeline.corpus"):
            load_corpus_daily(tmp_path, self.FACTS)

        assert "1999-00" in caplog.text
