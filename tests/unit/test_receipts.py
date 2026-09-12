"""Tests for pipeline.receipts (candidate selection, the target pool, the samples)."""

import logging
from pathlib import Path

import polars as pl
import pytest

from pipeline.receipts import (
    build_comment_samples,
    build_target_pool,
    load_receipt_verdicts,
    load_target_verdicts,
    measure_coverage,
    measure_precision,
    resolve_verdicts,
    samples_stamps,
    select_receipt_candidates,
)
from pipeline.schemas import (
    COMMENT_SAMPLES_SCHEMA,
    SENTIMENT_TARGETS_SCHEMA,
    TARGET_POOL_SCHEMA,
)
from utils.constants import (
    COMMENT_SAMPLES_MAX_BODY_CHARS,
    COMMENT_SAMPLES_MIN_CONFIDENCE,
    COMMENT_SAMPLES_TOP_N,
    TARGET_POOL_STRATA,
)
from utils.player_config import load_player_config_version

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


# Input contract of build_comment_samples: the attributed, fan-team-resolved
# frame aggregate_sentiment() holds. Pinned so an all-null team column
# can't infer as Null dtype.
_SAMPLES_INPUT_SCHEMA = pl.Schema(
    {
        "attributed_player": pl.String,
        "sentiment": pl.String,
        "sentiment_player": pl.String,
        "comment_id": pl.String,
        "link_id": pl.String,
        "body": pl.String,
        "score": pl.Int64,
        "confidence": pl.Float64,
        "created_utc": pl.Int64,
        "team": pl.String,
    }
)


def _samples_input(rows: list[dict]) -> pl.DataFrame:
    """Build a build_comment_samples input frame from row dicts, filling
    the columns a test doesn't care about with stable defaults.
    sentiment_player defaults to the row's attributed_player (a named
    target), so only the target-gate tests set it explicitly."""
    defaults = {
        "link_id": "t3_post1",
        "confidence": 0.95,
        "created_utc": 1704067200,
        "team": None,
    }
    return pl.DataFrame(
        [
            {
                "sentiment_player": row["attributed_player"],
                **defaults,
                **row,
            }
            for row in rows
        ],
        schema=_SAMPLES_INPUT_SCHEMA,
    )


class TestBuildCommentSamples:
    """Tests for build_comment_samples (the comment-samples fact subset)."""

    @pytest.fixture
    def cell_rows(self) -> list[dict]:
        """Twelve distinct LeBron/neg candidates with scores 12..1, bodies b12..b1
        (score k has body bk), all above the confidence floor and short."""
        return [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": f"c{k:02d}",
                "body": f"b{k}",
                "score": k,
            }
            for k in range(12, 0, -1)
        ]

    def test_conforms_to_schema(self, cell_rows):
        """The frame matches COMMENT_SAMPLES_SCHEMA exactly."""
        frame = build_comment_samples(_samples_input(cell_rows))

        assert frame.schema == COMMENT_SAMPLES_SCHEMA

    def test_caps_each_cell_at_n_by_score(self, cell_rows):
        """A cell keeps its top-n by score; rank follows score order."""
        frame = build_comment_samples(_samples_input(cell_rows), n=10)

        assert frame.height == 10
        assert frame["rank"].to_list() == list(range(1, 11))
        assert frame["score"].to_list() == list(range(12, 2, -1))
        assert frame["comment_id"][0] == "c12"

    def test_custom_n_honored(self, cell_rows):
        """n is a keyword parameter, not a baked constant."""
        frame = build_comment_samples(_samples_input(cell_rows), n=3)

        assert frame["rank"].to_list() == [1, 2, 3]

    def test_thin_cell_not_padded(self):
        """A cell with fewer than n candidates yields fewer rows, never padding."""
        rows = [
            {
                "attributed_player": "Stephen Curry",
                "sentiment": "pos",
                "comment_id": "c1",
                "body": "splash",
                "score": 4,
            },
            {
                "attributed_player": "Stephen Curry",
                "sentiment": "pos",
                "comment_id": "c2",
                "body": "greatest shooter",
                "score": 9,
            },
        ]
        frame = build_comment_samples(_samples_input(rows), n=10)

        assert frame.height == 2
        assert frame["rank"].to_list() == [1, 2]
        assert frame["comment_id"].to_list() == ["c2", "c1"]

    def test_confidence_floor_excludes_low_confidence(self):
        """A high-score row below the floor is not a candidate at all."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "viral",
                "body": "washed",
                "score": 5000,
                "confidence": 0.6,
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "solid",
                "body": "cooked",
                "score": 10,
                "confidence": 0.9,
            },
        ]
        frame = build_comment_samples(_samples_input(rows), min_confidence=0.9)

        assert frame["comment_id"].to_list() == ["solid"]
        assert frame["rank"].to_list() == [1]

    def test_confidence_floor_exempts_neutral(self):
        """The floor guards the polar labels only: a neu row at the
        classifier's conventional 0.5 is still a candidate."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neu",
                "comment_id": "neutral",
                "body": "LeBron had 28 tonight",
                "score": 40,
                "confidence": 0.5,
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "pos",
                "comment_id": "hedged",
                "body": "decent game I guess",
                "score": 40,
                "confidence": 0.5,
            },
        ]
        frame = build_comment_samples(_samples_input(rows), min_confidence=0.9)

        assert frame["comment_id"].to_list() == ["neutral"]

    def test_target_gate_excludes_polar_rows_without_target(self):
        """A polar row where the classifier declined to name a target is
        not a candidate, whatever its score; the next-best named-target
        row takes its rank."""
        rows = [
            {
                "attributed_player": "Rudy Gobert",
                "sentiment": "neg",
                "sentiment_player": None,
                "comment_id": "bystander",
                "body": "You were fouling Wemby all game",
                "score": 5000,
            },
            {
                "attributed_player": "Rudy Gobert",
                "sentiment": "neg",
                "comment_id": "named",
                "body": "classic Gobert defense",
                "score": 10,
            },
        ]
        frame = build_comment_samples(_samples_input(rows))

        assert frame["comment_id"].to_list() == ["named"]
        assert frame["rank"].to_list() == [1]

    def test_target_gate_exempts_neutral(self):
        """The gate guards the polar labels only: the classifier routinely
        omits the target on neutral comments, so a null-target neu row is
        still a candidate."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neu",
                "sentiment_player": None,
                "comment_id": "neutral",
                "body": "LeBron had 28 tonight",
                "score": 40,
            },
        ]
        frame = build_comment_samples(_samples_input(rows))

        assert frame["comment_id"].to_list() == ["neutral"]

    def test_candidacy_log_reports_target_gate(self, caplog):
        """The candidacy line reports the target gate's removals alongside
        the floor and cap."""
        rows = [
            {
                "attributed_player": "Rudy Gobert",
                "sentiment": "neg",
                "sentiment_player": None,
                "comment_id": "bystander",
                "body": "You were fouling Wemby all game",
                "score": 5000,
            },
            {
                "attributed_player": "Rudy Gobert",
                "sentiment": "neg",
                "comment_id": "named",
                "body": "classic Gobert defense",
                "score": 10,
            },
        ]
        with caplog.at_level(logging.INFO, logger="pipeline.receipts"):
            build_comment_samples(_samples_input(rows))

        assert "1 (50.0%) removed by the pos/neg target gate" in caplog.text

    def test_body_length_cap_excludes_long_bodies(self):
        """A high-score essay over the cap is not a candidate at all."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "essay",
                "body": "x" * 501,
                "score": 5000,
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "quip",
                "body": "x" * 500,
                "score": 10,
            },
        ]
        frame = build_comment_samples(_samples_input(rows), max_body_chars=500)

        assert frame["comment_id"].to_list() == ["quip"]

    def test_bodies_are_verbatim(self):
        """body is carried untouched — no truncation, no whitespace edits."""
        body = "  LeBron is  washed\n\nand it's not close  "
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "c1",
                "body": body,
                "score": 3,
            },
        ]
        frame = build_comment_samples(_samples_input(rows))

        assert frame["body"][0] == body

    def test_dedup_by_body_keeps_highest_scored(self):
        """Identical bodies within a cell collapse to the best-ranked copy."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "low",
                "body": "same copypasta",
                "score": 2,
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "high",
                "body": "same copypasta",
                "score": 20,
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "other",
                "body": "different",
                "score": 5,
            },
        ]
        frame = build_comment_samples(_samples_input(rows))

        assert frame["comment_id"].to_list() == ["high", "other"]
        assert frame["rank"].to_list() == [1, 2]

    def test_dedup_is_per_cell(self):
        """The same body under two players (or sentiments) is not a duplicate."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "c1",
                "body": "overrated",
                "score": 5,
            },
            {
                "attributed_player": "Kevin Durant",
                "sentiment": "neg",
                "comment_id": "c2",
                "body": "overrated",
                "score": 5,
            },
        ]
        frame = build_comment_samples(_samples_input(rows))

        assert frame.height == 2

    def test_tiebreak_score_then_confidence_then_comment_id(self):
        """Equal scores break on confidence desc, then comment_id asc."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "zz",
                "body": "a",
                "score": 7,
                "confidence": 0.99,
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "bb",
                "body": "b",
                "score": 7,
                "confidence": 0.95,
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "aa",
                "body": "c",
                "score": 7,
                "confidence": 0.95,
            },
        ]
        frame = build_comment_samples(_samples_input(rows))

        assert frame["comment_id"].to_list() == ["zz", "aa", "bb"]

    def test_null_score_ranks_last(self):
        """A null score never wins a cell: nulls sort last, so the true
        top-upvoted receipt keeps rank 1."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "nullscore",
                "body": "washed",
                "score": None,
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "real",
                "body": "cooked",
                "score": 12,
            },
        ]
        frame = build_comment_samples(_samples_input(rows))

        assert frame["comment_id"].to_list() == ["real", "nullscore"]

    def test_defaults_are_the_named_constants(self):
        """The kwarg defaults are the importable module constants, so the
        manifest can import them rather than retype the rule."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": f"c{k:02d}",
                "body": f"b{k}",
                "score": k,
            }
            for k in range(COMMENT_SAMPLES_TOP_N + 5, 0, -1)
        ]
        frame = build_comment_samples(_samples_input(rows))

        assert frame.height == COMMENT_SAMPLES_TOP_N
        assert COMMENT_SAMPLES_MIN_CONFIDENCE == 0.9
        assert COMMENT_SAMPLES_MAX_BODY_CHARS == 500

    def test_fan_team_role_marked_and_nullable(self):
        """The fact's team column ships as fan_team; unresolved flair stays null."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": "pos",
                "comment_id": "c1",
                "body": "goat",
                "score": 9,
                "team": "Los Angeles Lakers",
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "pos",
                "comment_id": "c2",
                "body": "king",
                "score": 4,
                "team": None,
            },
        ]
        frame = build_comment_samples(_samples_input(rows))

        assert "team" not in frame.columns
        assert frame["fan_team"].to_list() == ["Los Angeles Lakers", None]

    def test_all_three_sentiments_sampled(self):
        """pos, neg, and neu cells are all sampled — balanced by construction."""
        rows = [
            {
                "attributed_player": "LeBron James",
                "sentiment": s,
                "comment_id": f"c_{s}",
                "body": s,
                "score": 1,
            }
            for s in ("pos", "neg", "neu")
        ]
        frame = build_comment_samples(_samples_input(rows))

        assert sorted(frame["sentiment"].to_list()) == ["neg", "neu", "pos"]

    def test_sorted_by_player_sentiment_rank(self):
        """File order is (attributed_player, sentiment, rank), independent
        of input order and of score across cells."""
        rows = [
            {
                "attributed_player": "Stephen Curry",
                "sentiment": "pos",
                "comment_id": "c1",
                "body": "a",
                "score": 100,
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "pos",
                "comment_id": "c2",
                "body": "b",
                "score": 1,
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "c3",
                "body": "c",
                "score": 50,
            },
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": "c4",
                "body": "d",
                "score": 60,
            },
        ]
        frame = build_comment_samples(_samples_input(rows))

        assert frame.select("attributed_player", "sentiment", "rank").rows() == [
            ("LeBron James", "neg", 1),
            ("LeBron James", "neg", 2),
            ("LeBron James", "pos", 1),
            ("Stephen Curry", "pos", 1),
        ]
        assert frame["comment_id"].to_list() == ["c4", "c3", "c2", "c1"]

    def test_empty_input_returns_conforming_empty_frame(self):
        """No candidates (empty input, or everything gated out) still yields
        a schema-conforming frame — the unified validation loop runs on it."""
        empty = build_comment_samples(_samples_input([]))
        gated = build_comment_samples(
            _samples_input(
                [
                    {
                        "attributed_player": "LeBron James",
                        "sentiment": "neg",
                        "comment_id": "c1",
                        "body": "x",
                        "score": 1,
                        "confidence": 0.1,
                    },
                ]
            )
        )

        assert empty.height == 0 and empty.schema == COMMENT_SAMPLES_SCHEMA
        assert gated.height == 0 and gated.schema == COMMENT_SAMPLES_SCHEMA


# --- the verdict sidecar ---------------------------------------------------

_ALIAS_MAP = {
    "lebron james": "LeBron James",
    "lebron": "LeBron James",
    "anthony davis": "Anthony Davis",
    "ad": "Anthony Davis",
    "luka doncic": "Luka Doncic",
    "luka": "Luka Doncic",
}


def _verdicts(rows: list[dict]) -> pl.DataFrame:
    """Build a SENTIMENT_TARGETS_SCHEMA frame from row dicts with stable
    defaults: a valid candidate-stratum verdict at rank 1, confidence 0.9."""
    defaults = {
        "attributed_player": "LeBron James",
        "sentiment": "neg",
        "stratum": "candidate",
        "rank": 1,
        "target_confidence": 0.9,
        "valid": True,
        "input_tokens": 100,
        "output_tokens": 10,
    }
    return pl.DataFrame(
        [{**defaults, **row} for row in rows], schema=SENTIMENT_TARGETS_SCHEMA
    )


class TestResolveVerdicts:
    """Tests for resolve_verdicts (raw target string -> canonical player)."""

    def test_resolves_through_alias_map_with_normalization(self):
        """Case and punctuation variants of an alias resolve to the canonical name."""
        verdicts = _verdicts(
            [
                {"comment_id": "c1", "target_raw": "lebron"},
                {"comment_id": "c2", "target_raw": "LeBron James."},
                {"comment_id": "c3", "target_raw": "A.D."},
            ]
        )

        resolved = resolve_verdicts(verdicts, _ALIAS_MAP)

        assert resolved["target_player"].to_list() == [
            "LeBron James",
            "LeBron James",
            "Anthony Davis",
        ]

    def test_null_and_untracked_targets_resolve_to_null(self):
        """A null verdict and a string outside the alias map both yield null."""
        verdicts = _verdicts(
            [
                {"comment_id": "c1", "target_raw": None},
                {"comment_id": "c2", "target_raw": "Nico Harrison"},
            ]
        )

        resolved = resolve_verdicts(verdicts, _ALIAS_MAP)

        assert resolved["target_player"].to_list() == [None, None]

    def test_folded_column_resolves_diacritics_for_measurement_only(self):
        """A model-emitted accent leaves target_player unresolved but
        target_player_folded resolved (NFKD, ASCII) - the mechanical-loss
        class the diagnostics separate from real screens."""
        verdicts = _verdicts([{"comment_id": "c1", "target_raw": "Luka Dončić"}])

        resolved = resolve_verdicts(verdicts, _ALIAS_MAP)

        assert resolved["target_player"][0] is None
        assert resolved["target_player_folded"][0] == "Luka Doncic"

    def test_keeps_input_columns(self):
        """The two resolved columns are appended; nothing is dropped."""
        verdicts = _verdicts([{"comment_id": "c1", "target_raw": "lebron"}])

        resolved = resolve_verdicts(verdicts, _ALIAS_MAP)

        assert resolved.columns == [
            *SENTIMENT_TARGETS_SCHEMA.names(),
            "target_player",
            "target_player_folded",
        ]


class TestLoadTargetVerdicts:
    """Tests for load_target_verdicts (sidecar read, validation, stamps)."""

    STAMPS = {
        "classifier_target_model": "claude-sonnet-5",
        "classifier_target_prompt_version": "v1",
    }

    def _write(self, tmp_path, verdicts: pl.DataFrame, metadata: dict) -> Path:
        path = tmp_path / "sentiment_targets.parquet"
        verdicts.write_parquet(path, metadata=metadata)
        return path

    def test_returns_frame_and_classifier_stamps(self, tmp_path):
        """The frame is returned as written with the two classifier keys."""
        path = self._write(
            tmp_path,
            _verdicts([{"comment_id": "c1", "target_raw": "lebron"}]),
            {**self.STAMPS, "players_config_version": load_player_config_version()},
        )

        frame, stamps = load_target_verdicts(path)

        assert frame.height == 1
        assert stamps == self.STAMPS

    def test_rejects_wrong_schema(self, tmp_path):
        """A parquet that is not SENTIMENT_TARGETS_SCHEMA raises."""
        path = tmp_path / "sentiment_targets.parquet"
        pl.DataFrame({"comment_id": ["c1"]}).write_parquet(path)

        with pytest.raises(ValueError, match="sentiment_targets"):
            load_target_verdicts(path)

    def test_warns_on_players_config_drift(self, tmp_path, caplog):
        """A pool built under a stale players.yaml warns, as the fact does."""
        path = self._write(
            tmp_path,
            _verdicts([{"comment_id": "c1", "target_raw": "lebron"}]),
            {**self.STAMPS, "players_config_version": "0.1"},
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.receipts"):
            load_target_verdicts(path)

        assert "players_config_version drift" in caplog.text

    def test_warns_on_absent_classifier_stamps(self, tmp_path, caplog):
        """A sidecar with no verifier identity warns; stamps come back None."""
        path = self._write(
            tmp_path,
            _verdicts([{"comment_id": "c1", "target_raw": "lebron"}]),
            {"players_config_version": load_player_config_version()},
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.receipts"):
            _, stamps = load_target_verdicts(path)

        assert "no classifier identity" in caplog.text
        assert stamps == {
            "classifier_target_model": None,
            "classifier_target_prompt_version": None,
        }


class TestVerifiedAdmission:
    """Tests for build_comment_samples under a verdict sidecar (strict posture)."""

    def _rows(self) -> list[dict]:
        """Three LeBron/neg candidates c3 > c2 > c1 by score, all named."""
        return [
            {
                "attributed_player": "LeBron James",
                "sentiment": "neg",
                "comment_id": f"c{k}",
                "body": f"b{k}",
                "score": k,
            }
            for k in (3, 2, 1)
        ]

    def _samples(self, rows, verdict_rows):
        resolved = resolve_verdicts(_verdicts(verdict_rows), _ALIAS_MAP)
        return build_comment_samples(
            _samples_input(rows), verdicts=resolved, alias_map=_ALIAS_MAP
        )

    def test_affirmed_rows_ship_and_rerank(self):
        """Rows whose resolved target is the attributed player ship; rank is
        contiguous over the admitted rows, not the pre-admission ranking."""
        frame = self._samples(
            self._rows(),
            [
                {"comment_id": "c3", "target_raw": None},
                {"comment_id": "c2", "target_raw": "LeBron"},
                {"comment_id": "c1", "target_raw": "lebron james"},
            ],
        )

        assert frame["comment_id"].to_list() == ["c2", "c1"]
        assert frame["rank"].to_list() == [1, 2]

    @pytest.mark.parametrize(
        "verdict",
        [
            {"comment_id": "c3", "target_raw": None},
            {"comment_id": "c3", "target_raw": "Anthony Davis"},
            {"comment_id": "c3", "target_raw": "Nico Harrison"},
            {"comment_id": "c3", "target_raw": "Luka Dončić"},
            {"comment_id": "c3", "target_raw": "lebron", "valid": False},
        ],
        ids=["null_target", "other_tracked", "untracked", "unfolded", "invalid"],
    )
    def test_non_affirming_verdict_excludes(self, verdict):
        """Null, other-player, untracked, unresolved-accent, and unparsed
        verdicts all exclude the row; admission is on resolved match only."""
        frame = self._samples(self._rows()[:1], [verdict])

        assert frame.height == 0

    def test_missing_verdict_excludes(self):
        """Strict: a polar row with no sidecar row is not a receipt."""
        frame = self._samples(
            self._rows(), [{"comment_id": "c1", "target_raw": "lebron"}]
        )

        assert frame["comment_id"].to_list() == ["c1"]

    def test_verifier_readmits_unnamed_row(self):
        """A NULL-sentiment_player row the classifier's gate would drop ships
        when the verifier names the attributed player."""
        rows = self._rows()[:1]
        rows[0]["sentiment_player"] = None
        frame = self._samples(rows, [{"comment_id": "c3", "target_raw": "lebron"}])

        assert frame["comment_id"].to_list() == ["c3"]

    def test_free_gate_vetoes_a_different_tracked_target(self):
        """The classifier's own target, when it resolves to another tracked
        player, drops the row even though the verifier affirmed."""
        rows = self._rows()[:1]
        rows[0]["sentiment_player"] = "AD"
        frame = self._samples(rows, [{"comment_id": "c3", "target_raw": "lebron"}])

        assert frame.height == 0

    def test_free_gate_ignores_an_untracked_target(self):
        """A classifier target outside the alias map is not a veto."""
        rows = self._rows()[:1]
        rows[0]["sentiment_player"] = "Rich Paul"
        frame = self._samples(rows, [{"comment_id": "c3", "target_raw": "lebron"}])

        assert frame["comment_id"].to_list() == ["c3"]

    def test_neutral_rows_need_no_verdict(self):
        """Neutral rows are never verified and ship as before."""
        rows = self._rows()[:1]
        rows[0]["sentiment"] = "neu"
        rows[0]["sentiment_player"] = None
        frame = self._samples(rows, [])

        assert frame["comment_id"].to_list() == ["c3"]

    def test_polar_gates_still_apply(self):
        """The confidence floor and body cap gate an affirmed row as before."""
        rows = self._rows()[:1]
        rows[0]["confidence"] = 0.5
        frame = self._samples(rows, [{"comment_id": "c3", "target_raw": "lebron"}])

        assert frame.height == 0

    def test_verdicts_require_alias_map(self):
        """The free gate needs the alias map; passing verdicts alone raises."""
        resolved = resolve_verdicts(_verdicts([]), _ALIAS_MAP)

        with pytest.raises(ValueError, match="alias_map"):
            build_comment_samples(_samples_input(self._rows()), verdicts=resolved)

    def test_conforms_to_schema(self):
        """Verified output matches COMMENT_SAMPLES_SCHEMA exactly."""
        frame = self._samples(
            self._rows(), [{"comment_id": "c3", "target_raw": "lebron"}]
        )

        assert frame.schema == COMMENT_SAMPLES_SCHEMA


class TestMeasureCoverage:
    """Tests for measure_coverage (verdicts over the current gate-lifted pool)."""

    def test_full_coverage(self):
        """Every current pool row with a valid verdict -> (pool, pool)."""
        rows = _samples_input(_cell("LeBron James", "neg", 3))
        verdicts = _verdicts(
            [{"comment_id": f"Leneg{i:02d}", "target_raw": "lebron"} for i in range(3)]
        )

        assert measure_coverage(rows, verdicts, k=50) == (3, 3)

    def test_shortfall_counts_missing_and_invalid_as_unverified(self):
        """A pool row with no sidecar row, or an unparsed one, is uncovered."""
        rows = _samples_input(_cell("LeBron James", "neg", 3))
        verdicts = _verdicts(
            [
                {"comment_id": "Leneg00", "target_raw": "lebron"},
                {"comment_id": "Leneg01", "target_raw": "lebron", "valid": False},
            ]
        )

        assert measure_coverage(rows, verdicts, k=50) == (1, 3)

    def test_pool_is_gate_lifted_top_k(self):
        """The denominator is the top-k per cell with unnamed rows included."""
        rows = _samples_input(_cell("LeBron James", "neg", 5, named=False))

        assert measure_coverage(rows, _verdicts([]), k=2) == (0, 2)


class TestMeasurePrecision:
    """Tests for measure_precision (over the would-have-shipped top-n)."""

    def test_breakdown_and_precision(self):
        """Six would-have-shipped rows: affirmed, mechanical (accent), null,
        other tracked, untracked, and one with no verdict (excluded from
        both sides). precision = (affirmed + mechanical) / verified."""
        rows = _samples_input(_cell("Luka Doncic", "neg", 6))
        verdicts = _verdicts(
            [
                {"comment_id": "Luneg00", "target_raw": "Luka"},
                {"comment_id": "Luneg01", "target_raw": "Luka Dončić"},
                {"comment_id": "Luneg02", "target_raw": None},
                {"comment_id": "Luneg03", "target_raw": "Anthony Davis"},
                {"comment_id": "Luneg04", "target_raw": "Nico Harrison"},
            ]
        )

        result = measure_precision(rows, resolve_verdicts(verdicts, _ALIAS_MAP), n=10)

        assert result == {
            "would_have_shipped": 6,
            "verified": 5,
            "affirmed": 1,
            "mechanical": 1,
            "null_target": 1,
            "other_tracked": 1,
            "untracked": 1,
            "precision": 0.4,
        }

    def test_would_have_shipped_is_the_gate_on_top_n(self):
        """Unnamed rows and rows past rank n are not in the denominator."""
        rows = _samples_input(
            _cell("LeBron James", "neg", 3)
            + _cell("LeBron James", "pos", 2, named=False)
        )
        verdicts = _verdicts(
            [{"comment_id": f"Leneg{i:02d}", "target_raw": "lebron"} for i in range(3)]
        )

        result = measure_precision(rows, resolve_verdicts(verdicts, _ALIAS_MAP), n=2)

        assert result["would_have_shipped"] == 2
        assert result["precision"] == 1.0

    def test_no_verified_rows_yields_null_precision(self):
        """An empty intersection reports precision None rather than dividing."""
        rows = _samples_input(_cell("LeBron James", "neg", 2))

        result = measure_precision(
            rows, resolve_verdicts(_verdicts([]), _ALIAS_MAP), n=10
        )

        assert result["verified"] == 0
        assert result["precision"] is None


class TestLoadReceiptVerdicts:
    """Tests for load_receipt_verdicts (the two-level posture)."""

    def _sidecar(self, tmp_path, verdicts: pl.DataFrame) -> Path:
        path = tmp_path / "sentiment_targets.parquet"
        verdicts.write_parquet(
            path,
            metadata={
                "classifier_target_model": "claude-sonnet-5",
                "classifier_target_prompt_version": "v1",
                "players_config_version": load_player_config_version(),
            },
        )
        return path

    def test_absent_sidecar_falls_back_and_warns(self, tmp_path, caplog):
        """No file: verdicts None, receipts_verified False, the figures null."""
        rows = _samples_input(_cell("LeBron James", "neg", 2))

        with caplog.at_level(logging.WARNING, logger="pipeline.receipts"):
            verdicts, meta = load_receipt_verdicts(
                rows, tmp_path / "missing.parquet", _ALIAS_MAP
            )

        assert verdicts is None
        assert meta == {
            "receipts_verified": False,
            "receipts_coverage": None,
            "receipts_precision": None,
            "classifier_target_model": None,
            "classifier_target_prompt_version": None,
        }
        assert "receipts_verified" in caplog.text

    def test_none_path_falls_back(self, tmp_path):
        """No path at all is the same fallback."""
        rows = _samples_input(_cell("LeBron James", "neg", 2))

        verdicts, meta = load_receipt_verdicts(rows, None, _ALIAS_MAP)

        assert verdicts is None
        assert meta["receipts_verified"] is False

    def test_present_sidecar_is_strict_with_figures_and_stamps(self, tmp_path):
        """A sidecar yields resolved verdicts, coverage, precision, stamps."""
        rows = _samples_input(_cell("LeBron James", "neg", 2))
        path = self._sidecar(
            tmp_path,
            _verdicts(
                [
                    {"comment_id": "Leneg00", "target_raw": "lebron"},
                    {"comment_id": "Leneg01", "target_raw": None},
                ]
            ),
        )

        verdicts, meta = load_receipt_verdicts(rows, path, _ALIAS_MAP)

        assert "target_player" in verdicts.columns
        assert meta == {
            "receipts_verified": True,
            "receipts_coverage": 1.0,
            "receipts_precision": 0.5,
            "classifier_target_model": "claude-sonnet-5",
            "classifier_target_prompt_version": "v1",
        }

    def test_coverage_shortfall_warns(self, tmp_path, caplog):
        """A current pool row without a verdict is the top-up trigger."""
        rows = _samples_input(_cell("LeBron James", "neg", 2))
        path = self._sidecar(
            tmp_path, _verdicts([{"comment_id": "Leneg00", "target_raw": "lebron"}])
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.receipts"):
            _, meta = load_receipt_verdicts(rows, path, _ALIAS_MAP)

        assert meta["receipts_coverage"] == 0.5
        assert "coverage shortfall" in caplog.text
        assert "top up" in caplog.text

    def test_verified_with_no_shipped_row_verified_keeps_null_precision(self, tmp_path):
        """A sidecar that covers no would-have-shipped row is still the
        verified posture, with precision None rather than a division."""
        rows = _samples_input(_cell("LeBron James", "neg", 2, named=False))
        path = self._sidecar(
            tmp_path, _verdicts([{"comment_id": "Leneg00", "target_raw": "lebron"}])
        )

        _, meta = load_receipt_verdicts(rows, path, _ALIAS_MAP)

        assert meta["receipts_verified"] is True
        assert meta["receipts_precision"] is None


class TestSamplesStamps:
    """Tests for samples_stamps (the comment_samples parquet metadata)."""

    def test_verified_carries_flag_and_classifier_keys(self):
        """Verified: the flag plus both verifier identity keys, all strings."""
        meta = {
            "receipts_verified": True,
            "classifier_target_model": "claude-sonnet-5",
            "classifier_target_prompt_version": "v1",
        }

        assert samples_stamps(meta) == {
            "receipts_verified": "true",
            "classifier_target_model": "claude-sonnet-5",
            "classifier_target_prompt_version": "v1",
        }

    def test_unverified_carries_only_the_flag(self):
        """Fallback: the flag alone; no null-valued identity keys."""
        meta = {
            "receipts_verified": False,
            "classifier_target_model": None,
            "classifier_target_prompt_version": None,
        }

        assert samples_stamps(meta) == {"receipts_verified": "false"}
