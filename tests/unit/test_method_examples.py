"""
Tests for the method examples: the curated table, its slot checks, the scan.

Rows are described by their names found and the classifier's pick; the
attribution columns follow under the active configs, as in assembly.
Real-config dependent: the names used must stay tracked in players.yaml.
"""

import polars as pl
import pytest

from pipeline.method_examples import (
    MethodExamplesError,
    attribution_cases,
    build_method_examples,
    count_attribution_cases,
    scan_candidates,
)
from pipeline.receipts import resolve_verdicts
from pipeline.schemas import (
    ACCURACY_SAMPLE_SCHEMA,
    METHOD_EXAMPLES_SCHEMA,
    NULLABLE_COLUMNS,
    SENTIMENT_SCHEMA,
    SENTIMENT_TARGETS_SCHEMA,
    validate_nullability,
    validate_schema,
)
from utils.method_examples_config import SLOTS, MethodExampleSpec
from utils.player_config import (
    ATTRIBUTION_CASES,
    build_alias_to_player_map,
    classify_attribution,
    resolve_player,
)
from utils.team_config import build_alias_to_team_map, extract_team_from_flair

LEBRON, JOKIC, CURRY, TATUM = (
    "LeBron James",
    "Nikola Jokic",
    "Stephen Curry",
    "Jayson Tatum",
)
IDS = {LEBRON: 2544, JOKIC: 203999, CURRY: 201939, TATUM: 1628369}
LAKERS = ":lal-1: Lakers"

# comment_id -> (names found, pick, sentiment, confidence, flair)
ROWS: dict[str, tuple[list[str], str | None, str, float, str | None]] = {
    "t1": ([LEBRON, JOKIC], "Jokic", "neg", 0.9, LAKERS),
    "c1": ([LEBRON], None, "neu", 0.5, None),
    "c2": ([LEBRON], "Jokic", "neg", 0.8, None),
    "c3": ([LEBRON, JOKIC], "Stephen Curry", "pos", 0.9, None),
    "c4": ([LEBRON, JOKIC], None, "neu", 0.5, None),
    "c5": ([LEBRON, JOKIC], "Scottie Pippen", "neg", 0.7, None),
    "n0": ([], None, "neu", 0.5, None),
    "r1": ([TATUM], "Tatum", "pos", 0.95, None),
    "s1": ([LEBRON], "LeBron", "pos", 0.9, None),
    "s2": ([LEBRON], "LeBron", "neg", 0.9, None),
    "s3": ([LEBRON], None, "neu", 0.5, None),
    "s4": ([LEBRON], "LeBron", "neg", 0.9, None),
    "q1": ([LEBRON], "LeBron", "neg", 0.95, None),
    "q2": ([LEBRON], "LeBron", "pos", 0.95, None),
    "x1": ([LEBRON], "LeBron", "neg", 0.95, None),
    "x2": ([LEBRON], "LeBron", "neg", 0.6, None),
}

GOOD = [
    ("trace", "t1"),
    ("case", "c1"),
    ("case", "c2"),
    ("case", "c3"),
    ("case", "c4"),
    ("case", "c5"),
    ("read", "r1"),
    ("slip", "s1"),
    ("slip", "s2"),
    ("slip", "s3"),
    ("quote_check", "q1"),
    ("quote_check", "q2"),
]


def _specs(entries: list[tuple[str, str]]) -> tuple[MethodExampleSpec, ...]:
    return tuple(MethodExampleSpec(slot, comment_id) for slot, comment_id in entries)


@pytest.fixture(scope="module")
def alias_map() -> dict[str, str]:
    return build_alias_to_player_map()


@pytest.fixture(scope="module")
def fact(alias_map) -> pl.DataFrame:
    """The ROWS as a usable fact with player_id attached."""
    team_map = build_alias_to_team_map()
    ids = list(ROWS)
    rows = {
        "comment_id": ids,
        "body": [f"body of {i}" for i in ids],
        "author": ["u"] * len(ids),
        "author_flair_text": [ROWS[i][4] for i in ids],
        "author_flair_css_class": [None] * len(ids),
        "created_utc": [1704067200 + n for n in range(len(ids))],
        "score": [100 - n for n in range(len(ids))],
        "link_id": ["t3_post"] * len(ids),
        "mentioned_players": [ROWS[i][0] for i in ids],
        "mentioned_text": [[name.split()[-1] for name in ROWS[i][0]] for i in ids],
        "sentiment": [ROWS[i][2] for i in ids],
        "confidence": [ROWS[i][3] for i in ids],
        "sentiment_player": [ROWS[i][1] for i in ids],
        "attributed_player": [
            resolve_player(ROWS[i][0], ROWS[i][1], alias_map) for i in ids
        ],
        "fan_team": [extract_team_from_flair(ROWS[i][4], team_map) for i in ids],
        "input_tokens": [1] * len(ids),
        "output_tokens": [1] * len(ids),
    }
    df = pl.DataFrame(rows, schema=SENTIMENT_SCHEMA)
    return df.with_columns(
        pl.col("attributed_player")
        .replace_strict(IDS, default=None, return_dtype=pl.Int64)
        .alias("player_id")
    )


@pytest.fixture(scope="module")
def verdicts(alias_map) -> pl.DataFrame:
    """q1 names Jokic, q2 names nobody, x1 affirms LeBron, x2 is invalid."""
    raw = pl.DataFrame(
        {
            "comment_id": ["q1", "q2", "x1", "x2"],
            "attributed_player": [LEBRON] * 4,
            "sentiment": ["neg", "pos", "neg", "neg"],
            "stratum": ["candidate"] * 4,
            "rank": [1, 2, 3, 4],
            "target_raw": ["Jokic", None, "LeBron", "??"],
            "target_confidence": [0.9] * 4,
            "valid": [True, True, True, False],
            "input_tokens": [1] * 4,
            "output_tokens": [1] * 4,
        },
        schema=SENTIMENT_TARGETS_SCHEMA,
    )
    return resolve_verdicts(raw, alias_map)


@pytest.fixture(scope="module")
def sample() -> pl.DataFrame:
    """s1 a sentiment slip, s2 a target slip, s3 quiet approval, s4 agrees; r1 unsure."""
    return pl.DataFrame(
        {
            "comment_id": ["s1", "s2", "s3", "s4", "r1"],
            "group": ["first"] * 5,
            "position": [0, 1, 2, 3, 4],
            "mention_count": [1] * 5,
            "sentiment": ["pos", "neg", "neu", "neg", "pos"],
            "confidence": [0.9, 0.9, 0.5, 0.9, 0.95],
            "sentiment_player": ["LeBron", "LeBron", None, "LeBron", "Tatum"],
            "attributed_player": [LEBRON, LEBRON, LEBRON, LEBRON, TATUM],
            "labeled": [True] * 5,
            "label_sentiment": ["neg", "neg", "pos", "neg", "neg"],
            "label_target": [LEBRON, "none", LEBRON, LEBRON, TATUM],
            "reject": [None] * 5,
            "needed_context": [False] * 5,
            "unsure": [False, False, False, False, True],
            "note": [None] * 5,
        },
        schema=ACCURACY_SAMPLE_SCHEMA,
    )


def _build(fact, specs, alias_map, verdicts, sample) -> pl.DataFrame:
    return build_method_examples(
        fact, _specs(specs), alias_map=alias_map, verdicts=verdicts, sample=sample
    )


class TestAttributionCases:
    """The vectorized derivation against the row-level rule."""

    def test_agrees_with_classify_attribution_on_every_row(self, fact, alias_map):
        """Every branch in the fixture lands where classify_attribution puts it."""
        cases = attribution_cases(fact, alias_map)

        for mentions, pick, case in cases.select(
            "mentioned_players", "sentiment_player", "attribution_case"
        ).iter_rows():
            assert case == classify_attribution(mentions, pick, alias_map)

    def test_fixture_covers_every_branch(self, fact, alias_map):
        """The fixture is only a test of the rule if it reaches all seven branches."""
        cases = attribution_cases(fact, alias_map)

        assert set(cases["attribution_case"].to_list()) == set(ATTRIBUTION_CASES)

    def test_row_order_kept(self, fact, alias_map):
        """The join back from the resolved picks keeps the fact's order."""
        cases = attribution_cases(fact, alias_map)

        assert cases["comment_id"].to_list() == fact["comment_id"].to_list()

    def test_counts_list_every_case(self, fact, alias_map):
        """Every case is a row, zero where the frame has none, in vocabulary order."""
        counts = count_attribution_cases(attribution_cases(fact.head(1), alias_map))

        assert counts["attribution_case"].to_list() == list(ATTRIBUTION_CASES)
        assert counts["rows"].to_list() == [0, 0, 0, 1, 0, 0, 0]


class TestBuildMethodExamples:
    """The table and its checks."""

    def test_empty_curation_is_an_empty_table(self, fact, alias_map):
        """A season that curates nothing gets the schema with no rows, unchecked."""
        out = build_method_examples(
            fact, (), alias_map=alias_map, verdicts=None, sample=None
        )

        assert out.schema == METHOD_EXAMPLES_SCHEMA
        assert out.height == 0

    def test_conforms_in_config_order(self, fact, alias_map, verdicts, sample):
        """The good curation builds, conforms, and keeps the page order."""
        out = _build(fact, GOOD, alias_map, verdicts, sample)

        validate_schema(out, METHOD_EXAMPLES_SCHEMA, "method_examples")
        validate_nullability(
            out, NULLABLE_COLUMNS["method_examples"], "method_examples"
        )
        assert out["comment_id"].to_list() == [c for _, c in GOOD]
        assert out["position"].to_list() == list(range(len(GOOD)))
        assert out["slot"].to_list() == [s for s, _ in GOOD]

    def test_author_is_not_a_column(self):
        """The commenter never leaves the pipeline."""
        assert "author" not in METHOD_EXAMPLES_SCHEMA.names()

    def test_joined_columns(self, fact, alias_map, verdicts, sample):
        """Verdict and label columns are filled inside their pools and null outside."""
        out = _build(fact, GOOD, alias_map, verdicts, sample)
        rows = {r["comment_id"]: r for r in out.to_dicts()}

        assert rows["q1"]["target_raw"] == "Jokic"
        assert rows["q1"]["verified_target"] == JOKIC
        assert rows["q2"]["verified_target"] is None
        assert rows["t1"]["target_raw"] is None
        assert rows["s2"]["label_target"] == "none"
        assert rows["s3"]["label_sentiment"] == "pos"
        assert rows["t1"]["label_sentiment"] is None
        assert rows["t1"]["attribution_case"] == "several_resolved"
        assert rows["t1"]["player_id"] == IDS[JOKIC]
        assert rows["c4"]["attributed_player"] is None
        assert rows["c4"]["player_id"] is None
        assert rows["t1"]["mentioned_text"] == ["James", "Jokic"]

    @pytest.mark.parametrize(
        "swap,match",
        [
            (("trace", "t1", "zz"), "trace zz: not in the fact"),
            (("trace", "t1", "c1"), "trace c1: the slot requires several_resolved"),
            (("trace", "t1", "c3"), "trace c3: the slot requires several_resolved"),
            (("read", "r1", "c4"), "read c4: the slot requires attributed"),
            (("slip", "s1", "s4"), "slip s4: the slot requires a scored"),
            (("slip", "s1", "r1"), "slip r1: the slot requires a scored"),
            (("slip", "s1", "x2"), "slip x2: the slot requires a scored"),
            (("quote_check", "q1", "x1"), "quote_check x1: the slot requires"),
            (("quote_check", "q1", "x2"), "quote_check x2: the slot requires"),
            (
                ("case", "c1", "n0"),
                "case n0: the slot requires an attribution case other",
            ),
        ],
    )
    def test_row_that_does_not_fit_fails_by_name(
        self, fact, alias_map, verdicts, sample, swap, match
    ):
        """One comment swapped for one that fails its slot's check names the comment."""
        slot, old, new = swap
        specs = [(s, new if c == old else c) for s, c in GOOD]

        with pytest.raises(MethodExamplesError, match=match):
            _build(fact, specs, alias_map, verdicts, sample)

    def test_trace_needs_a_fan_team(self, fact, alias_map, verdicts, sample):
        """A several_resolved row without a flair cannot carry the walkthrough."""
        unflaired = fact.with_columns(
            pl.when(pl.col("comment_id") == "t1")
            .then(None)
            .otherwise(pl.col("fan_team"))
            .alias("fan_team")
        )

        with pytest.raises(MethodExamplesError, match="trace t1: the slot requires"):
            _build(unflaired, GOOD, alias_map, verdicts, sample)

    @pytest.mark.parametrize(
        "entries,match",
        [
            (GOOD + [("trace", "c3")], "trace c3: the slot requires"),
            ([e for e in GOOD if e != ("slip", "s2")], "slip: 3 row"),
            ([e for e in GOOD if e != ("quote_check", "q2")], "quote_check: 2 row"),
            ([e for e in GOOD if e != ("read", "r1")], "read: at least one"),
            ([e for e in GOOD if e != ("case", "c5")], "case: one row per branch"),
            (GOOD + [("case", "s4")], "case: one row per branch"),
        ],
    )
    def test_counts_and_coverage(
        self, fact, alias_map, verdicts, sample, entries, match
    ):
        """Fixed slots take their exact count; the case slot takes every branch once."""
        with pytest.raises(MethodExamplesError, match=match):
            _build(fact, entries, alias_map, verdicts, sample)

    def test_case_slot_follows_the_fact(self, fact, alias_map, verdicts, sample):
        """A branch the fact lacks is not required: c5 drops with the only unresolved row."""
        without = fact.filter(pl.col("comment_id") != "c5")
        entries = [e for e in GOOD if e != ("case", "c5")]

        out = _build(without, entries, alias_map, verdicts, sample)

        assert out.filter(pl.col("slot") == "case").height == 4

    def test_slips_need_a_quiet_approval_row(self, fact, alias_map, verdicts, sample):
        """Three slips without a manual-positive, classifier-neutral row are refused."""
        entries = [("slip", "s4") if e == ("slip", "s3") else e for e in GOOD]
        agreeing = sample.with_columns(
            pl.when(pl.col("comment_id") == "s4")
            .then(pl.lit("pos"))
            .otherwise(pl.col("label_sentiment"))
            .alias("label_sentiment")
        )

        with pytest.raises(MethodExamplesError, match="quiet-approval"):
            _build(fact, entries, alias_map, verdicts, agreeing)

    def test_without_a_sidecar_no_quote_check_fits(self, fact, alias_map, sample):
        """No verdicts, no rejected receipts to show."""
        with pytest.raises(MethodExamplesError, match="quote_check q1"):
            _build(fact, GOOD, alias_map, None, sample)

    def test_without_a_sample_no_slip_fits(self, fact, alias_map, verdicts):
        """No manual labels, no slips to show."""
        with pytest.raises(MethodExamplesError, match="slip s1"):
            _build(fact, GOOD, alias_map, verdicts, None)


class TestScanCandidates:
    """The per-slot report the picks are made from."""

    def test_one_frame_per_slot_with_a_curation_line(
        self, fact, alias_map, verdicts, sample
    ):
        """Every slot reports, and each row carries its paste-ready entry."""
        report = scan_candidates(
            fact, alias_map=alias_map, verdicts=verdicts, sample=sample
        )

        assert list(report) == list(SLOTS)
        trace = report["trace"]
        assert trace["comment_id"].to_list() == ["t1"]
        assert trace["curation"].to_list() == ["- {slot: trace, comment_id: t1}"]

    def test_every_candidate_builds_in_its_slot(
        self, fact, alias_map, verdicts, sample
    ):
        """A reported row passes its slot's check: the report never misleads."""
        report = scan_candidates(
            fact, alias_map=alias_map, verdicts=verdicts, sample=sample
        )

        assert set(report["read"]["comment_id"].to_list()) >= {"r1", "s1", "q1"}
        assert set(report["slip"]["comment_id"].to_list()) == {"s1", "s2", "s3"}
        assert set(report["quote_check"]["comment_id"].to_list()) == {"q1", "q2"}
        assert set(report["case"]["attribution_case"].to_list()) == set(
            ATTRIBUTION_CASES
        ) - {
            "several_resolved",
            "no_name",
        }

    def test_case_slot_capped_per_branch(self, fact, alias_map, verdicts, sample):
        """The cap applies within each branch, so a rare branch still shows."""
        report = scan_candidates(
            fact, alias_map=alias_map, verdicts=verdicts, sample=sample, per_slot=1
        )
        case = report["case"]

        assert case.height == 5
        assert case.filter(pl.col("attribution_case") == "one_name")[
            "comment_id"
        ].to_list() == ["c1"]

    def test_long_bodies_are_not_candidates(self, fact, alias_map, verdicts, sample):
        """A body over the receipts' cap is left out: an example is a quote."""
        long = fact.with_columns(
            pl.when(pl.col("comment_id") == "t1")
            .then(pl.lit("x" * 501))
            .otherwise(pl.col("body"))
            .alias("body")
        )

        report = scan_candidates(
            long, alias_map=alias_map, verdicts=verdicts, sample=sample
        )

        assert report["trace"].height == 0
