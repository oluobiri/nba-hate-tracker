"""Tests for pipeline.receipts (candidate selection and the target pool)."""

import polars as pl
import pytest

from pipeline.receipts import build_target_pool, select_receipt_candidates
from pipeline.schemas import TARGET_POOL_SCHEMA
from utils.constants import TARGET_POOL_STRATA

_INPUT_SCHEMA = pl.Schema(
    {
        "attributed_player": pl.String,
        "sentiment": pl.String,
        "sentiment_player": pl.String,
        "comment_id": pl.String,
        "body": pl.String,
        "score": pl.Int64,
        "confidence": pl.Float64,
    }
)


def _frame(rows: list[dict]) -> pl.DataFrame:
    """Build an attributed frame from row dicts with stable defaults.

    sentiment_player defaults to the attributed player (a named target);
    pass None explicitly for an unnamed row.
    """
    defaults = {"confidence": 0.95, "score": 1}
    return pl.DataFrame(
        [
            {"sentiment_player": row["attributed_player"], **defaults, **row}
            for row in rows
        ],
        schema=_INPUT_SCHEMA,
    )


def _cell(player: str, sentiment: str, count: int, *, named: bool = True) -> list:
    """count rows for one cell, scores descending so ranks are predictable."""
    return [
        {
            "attributed_player": player,
            "sentiment": sentiment,
            "sentiment_player": player if named else None,
            "comment_id": f"{player[:2]}{sentiment}{i:02d}",
            "body": f"{player} {sentiment} comment {i}",
            "score": 100 - i,
        }
        for i in range(count)
    ]


class TestSelectReceiptCandidates:
    """Tests for select_receipt_candidates."""

    def test_ranks_within_cell_and_caps_at_n(self):
        """Verify rank is 1..n per cell by score and rows past n are dropped."""
        df = _frame(_cell("Luka Doncic", "neg", 5) + _cell("Luka Doncic", "pos", 2))

        out = select_receipt_candidates(df, n=3)

        neg = out.filter(pl.col("sentiment") == "neg").sort("rank")
        assert neg["rank"].to_list() == [1, 2, 3]
        assert neg["comment_id"].to_list() == ["Luneg00", "Luneg01", "Luneg02"]
        assert out.filter(pl.col("sentiment") == "pos")["rank"].to_list() == [1, 2]

    def test_target_gate_on_drops_unnamed_polar_rows(self):
        """Verify the default gate removes polar rows with no sentiment_player."""
        df = _frame(
            _cell("Luka Doncic", "neg", 2, named=False) + _cell("Luka Doncic", "neg", 1)
        )

        out = select_receipt_candidates(df, n=10)

        assert out["comment_id"].to_list() == ["Luneg00"]

    def test_target_gate_off_ranks_named_and_unnamed_together(self):
        """Verify lifting the gate lets unnamed rows compete on score."""
        unnamed = _cell("Luka Doncic", "neg", 2, named=False)
        named = _cell("Luka Doncic", "neg", 1)
        named[0].update(comment_id="named", score=50, body="a distinct named body")

        out = select_receipt_candidates(
            _frame(unnamed + named), n=10, require_target=False
        )

        assert out.sort("rank")["comment_id"].to_list() == [
            "Luneg00",
            "Luneg01",
            "named",
        ]

    def test_keeps_input_columns_plus_rank(self):
        """Verify the output is the input's columns with rank appended."""
        df = _frame(_cell("Luka Doncic", "neg", 1))

        out = select_receipt_candidates(df, n=1)

        assert out.columns == [*df.columns, "rank"]


class TestBuildTargetPool:
    """Tests for build_target_pool."""

    def _attributed(self) -> pl.DataFrame:
        """Two players, candidates deeper than k, named and unnamed rows, one neutral."""
        rows = (
            _cell("Luka Doncic", "neg", 6)
            + _cell("Luka Doncic", "neg", 4, named=False)
            + _cell("Anthony Davis", "pos", 3)
            + [
                {
                    "attributed_player": "Anthony Davis",
                    "sentiment": "neu",
                    "comment_id": "neutral",
                    "body": "AD played",
                }
            ]
        )
        # Make the unnamed ids distinct from the named ones
        for i, row in enumerate(rows[6:10]):
            row["comment_id"] = f"Lunull{i:02d}"
            row["score"] = 200 - i
        return _frame(rows)

    def test_conforms_to_schema(self):
        """Verify the pool matches TARGET_POOL_SCHEMA exactly."""
        pool = build_target_pool(self._attributed(), k=3, stratum_n=2)

        assert pool.schema == TARGET_POOL_SCHEMA

    def test_candidates_are_top_k_with_gate_lifted(self):
        """Verify unnamed rows outrank named ones on score when the gate is off."""
        pool = build_target_pool(self._attributed(), k=3, stratum_n=0)

        luka_neg = pool.filter(
            (pl.col("attributed_player") == "Luka Doncic")
            & (pl.col("stratum") == "candidate")
        ).sort("rank")
        assert luka_neg["comment_id"].to_list() == ["Lunull00", "Lunull01", "Lunull02"]
        assert luka_neg["rank"].to_list() == [1, 2, 3]

    def test_neutral_rows_never_enter_the_pool(self):
        """Verify only polar rows are verified."""
        pool = build_target_pool(self._attributed(), k=10, stratum_n=10)

        assert "neutral" not in pool["comment_id"].to_list()
        assert set(pool["sentiment"].to_list()) <= {"pos", "neg"}

    def test_strata_are_named_and_unnamed_non_candidates(self):
        """Verify each random stratum draws from the right class and excludes candidates."""
        df = self._attributed()
        pool = build_target_pool(df, k=2, stratum_n=10)
        candidates = set(pool.filter(pl.col("stratum") == "candidate")["comment_id"])
        named_ids = set(
            df.filter(pl.col("sentiment_player").is_not_null())["comment_id"]
        )

        random_named = pool.filter(pl.col("stratum") == "random_named")
        random_null = pool.filter(pl.col("stratum") == "random_null")
        assert set(random_named["comment_id"]) <= named_ids - candidates
        assert set(random_null["comment_id"]).isdisjoint(named_ids | candidates)
        assert random_named["rank"].null_count() == random_named.height
        assert set(pool["stratum"]) <= set(TARGET_POOL_STRATA)

    def test_one_row_per_comment(self):
        """Verify a comment appears once even when strata could redraw it."""
        pool = build_target_pool(self._attributed(), k=2, stratum_n=100)

        assert pool["comment_id"].n_unique() == pool.height

    def test_stratum_size_capped_by_availability(self):
        """Verify a stratum larger than its class yields every eligible row, no error."""
        df = self._attributed()
        pool = build_target_pool(df, k=1, stratum_n=100)

        unnamed_polar = df.filter(
            pl.col("sentiment_player").is_null() & (pl.col("sentiment") != "neu")
        )
        drawn = pool.filter(pl.col("stratum") == "random_null").height
        assert (
            drawn == unnamed_polar.height - 1
        )  # one unnamed row is the rank-1 candidate

    @pytest.mark.parametrize("seed", [7, 8])
    def test_deterministic_for_a_seed(self, seed: int):
        """Verify the same seed reproduces the same pool."""
        df = self._attributed()

        first = build_target_pool(df, k=2, stratum_n=2, seed=seed)
        second = build_target_pool(df, k=2, stratum_n=2, seed=seed)

        assert first.equals(second)
