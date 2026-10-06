"""
The method examples: curated comments published with what the pipeline stored for them.

config/<season>/method_examples.yaml names a comment per slot of the How
it works page; this module joins each to the fact, the verifier's verdict
and the manual label, derives its attribution case, and checks that it
fits its slot before anything is written. A comment that no longer fits
(an alias change gave a one-name example a second name) fails the build
by name instead of shipping a wrong caption.

The scan reports, per slot, the fact rows that would pass that slot's
check, so the picks are made from evidence; the report is a reference
file, never published.
"""

import logging
from collections.abc import Sequence

import polars as pl

from pipeline.schemas import METHOD_EXAMPLES_SCHEMA
from utils.constants import (
    COMMENT_SAMPLES_MAX_BODY_CHARS,
    COMMENT_SAMPLES_MIN_CONFIDENCE,
)
from utils.method_examples_config import SLOTS, MethodExampleSpec
from utils.player_config import ATTRIBUTION_CASES, resolve_sentiment_player

logger = logging.getLogger(__name__)

POLAR_SENTIMENTS = ("pos", "neg")
TRACE_CASE = "several_resolved"
# Branches the case slot never shows: the trace covers one, the page's
# rule has nothing to say about a comment with no name found
CASE_SLOT_EXCLUDED = frozenset({TRACE_CASE, "no_name"})
EXACT_SLOT_COUNTS = {"trace": 1, "slip": 3, "quote_check": 2}
QUIET_APPROVAL = {"label_sentiment": "pos", "sentiment": "neu"}
SCAN_PER_SLOT = 40

_VERDICT_COLUMNS = ["target_raw", "verified_target"]
_LABEL_COLUMNS = ["label_sentiment", "label_target"]
_HELPER_COLUMNS = ["verdict_valid", "label_scored"]


class MethodExamplesError(ValueError):
    """A curated example does not fit its slot, or the curation is incomplete."""


def attribution_cases(df: pl.DataFrame, alias_map: dict[str, str]) -> pl.DataFrame:
    """
    Add attribution_case to a fact frame, the rule of utils.player_config.classify_attribution.

    Vectorized for the whole fact: the classifier's picks are resolved
    once per distinct string and joined back, and the branch follows
    from the names found, the raw pick and the resolved pick.

    Args:
        df: Fact rows with mentioned_players and sentiment_player.
        alias_map: Lowercase alias -> canonical name.

    Returns:
        df with attribution_case appended.
    """
    picks = df.select(pl.col("sentiment_player").unique()).with_columns(
        pl.col("sentiment_player")
        .map_elements(
            lambda name: resolve_sentiment_player(name, alias_map),
            return_dtype=pl.String,
        )
        .alias("_pick")
    )
    names = pl.col("mentioned_players")
    count = names.list.len().fill_null(0)
    pick, raw = pl.col("_pick"), pl.col("sentiment_player")
    case = (
        pl.when(count == 0)
        .then(pl.lit("no_name"))
        .when(count == 1)
        .then(
            pl.when(raw.is_null() | (pick == names.list.first()))
            .then(pl.lit("one_name"))
            .otherwise(pl.lit("one_name_other_pick"))
        )
        .when(pick.is_null())
        .then(
            pl.when(raw.is_null())
            .then(pl.lit("several_no_pick"))
            .otherwise(pl.lit("several_unresolved"))
        )
        .when(names.list.contains(pick))
        .then(pl.lit(TRACE_CASE))
        .otherwise(pl.lit("several_resolved_unlisted"))
    )
    return (
        df.join(
            picks,
            on="sentiment_player",
            how="left",
            nulls_equal=True,
            maintain_order="left",
        )
        .with_columns(case.alias("attribution_case"))
        .drop("_pick")
    )


def count_attribution_cases(df: pl.DataFrame) -> pl.DataFrame:
    """
    Rows per attribution case, every case listed, in ATTRIBUTION_CASES order.

    Args:
        df: Frame with attribution_case.

    Returns:
        Frame of (attribution_case, rows).
    """
    counts = df.group_by("attribution_case").agg(pl.len().cast(pl.Int64).alias("rows"))
    return (
        pl.DataFrame({"attribution_case": list(ATTRIBUTION_CASES)})
        .join(counts, on="attribution_case", how="left")
        .with_columns(pl.col("rows").fill_null(0))
    )


def annotate(
    df: pl.DataFrame,
    *,
    alias_map: dict[str, str],
    verdicts: pl.DataFrame | None,
    sample: pl.DataFrame | None,
) -> pl.DataFrame:
    """
    Attach to fact rows everything the slots are judged on.

    Adds attribution_case; target_raw, verified_target and verdict_valid
    from the verifier (null outside its pool; verified_target only for a
    valid verdict); label_sentiment, label_target and label_scored from
    the accuracy sample (null outside it; scored means labeled, not
    rejected and not marked unsure).

    Args:
        df: Fact rows, with player_id attached.
        alias_map: Lowercase alias -> canonical name.
        verdicts: Resolved verdict sidecar (pipeline.receipts.resolve_verdicts), or None.
        sample: Accuracy sample conforming to ACCURACY_SAMPLE_SCHEMA, or None.

    Returns:
        df with the derived and joined columns appended.
    """
    out = attribution_cases(df, alias_map)

    if verdicts is None:
        out = out.with_columns(
            pl.lit(None, dtype=pl.String).alias("target_raw"),
            pl.lit(None, dtype=pl.String).alias("verified_target"),
            pl.lit(None, dtype=pl.Boolean).alias("verdict_valid"),
        )
    else:
        side = verdicts.select(
            "comment_id",
            "target_raw",
            pl.when(pl.col("valid"))
            .then(pl.col("target_player"))
            .alias("verified_target"),
            pl.col("valid").alias("verdict_valid"),
        )
        out = out.join(side, on="comment_id", how="left", maintain_order="left")

    if sample is None:
        out = out.with_columns(
            pl.lit(None, dtype=pl.String).alias("label_sentiment"),
            pl.lit(None, dtype=pl.String).alias("label_target"),
            pl.lit(None, dtype=pl.Boolean).alias("label_scored"),
        )
    else:
        side = sample.select(
            "comment_id",
            "label_sentiment",
            "label_target",
            (pl.col("labeled") & pl.col("reject").is_null() & ~pl.col("unsure")).alias(
                "label_scored"
            ),
        )
        out = out.join(side, on="comment_id", how="left", maintain_order="left")
    return out


# Each slot's row check as (what the build requires, the predicate).
_ATTRIBUTED = pl.col("attributed_player").is_not_null()
SLOT_CHECKS: dict[str, tuple[str, pl.Expr]] = {
    "trace": (
        f"{TRACE_CASE} with a fan team",
        (pl.col("attribution_case") == TRACE_CASE) & pl.col("fan_team").is_not_null(),
    ),
    "case": (
        f"an attribution case other than {', '.join(sorted(CASE_SLOT_EXCLUDED))}",
        ~pl.col("attribution_case").is_in(list(CASE_SLOT_EXCLUDED)),
    ),
    "read": ("attributed to one player", _ATTRIBUTED),
    "slip": (
        "a scored accuracy-sample row where the classifier and the manual label disagree",
        pl.col("label_scored").fill_null(False)
        & (
            (pl.col("sentiment") != pl.col("label_sentiment"))
            | (pl.col("attributed_player") != pl.col("label_target"))
        ),
    ),
    "quote_check": (
        "positive or negative at or above the quote floor, with a valid verdict "
        "naming someone other than the attributed player",
        pl.col("sentiment").is_in(list(POLAR_SENTIMENTS))
        & (pl.col("confidence") >= COMMENT_SAMPLES_MIN_CONFIDENCE)
        & _ATTRIBUTED
        & pl.col("verdict_valid").fill_null(False)
        & (
            pl.col("verified_target").is_null()
            | (pl.col("verified_target") != pl.col("attributed_player"))
        ),
    ),
}
assert set(SLOT_CHECKS) == set(SLOTS)


def _required_cases(annotated: pl.DataFrame) -> set[str]:
    """The case slot's required set: every branch the fact contains, less the excluded."""
    present = set(annotated.get_column("attribution_case").unique().to_list())
    return present - CASE_SLOT_EXCLUDED


def build_method_examples(
    df: pl.DataFrame,
    specs: Sequence[MethodExampleSpec],
    *,
    alias_map: dict[str, str],
    verdicts: pl.DataFrame | None,
    sample: pl.DataFrame | None,
) -> pl.DataFrame:
    """
    Build method_examples.parquet from the curated list, checking every slot.

    Args:
        df: The usable fact with player_id attached (error rows dropped).
        specs: The curated entries, in page order.
        alias_map: Lowercase alias -> canonical name.
        verdicts: Resolved verdict sidecar, or None.
        sample: Accuracy sample, or None.

    Returns:
        Frame conforming to METHOD_EXAMPLES_SCHEMA, in config order; empty
        when nothing is curated.

    Raises:
        MethodExamplesError: If a curated comment is not in the fact, does
            not fit its slot, or a slot's count, coverage or uniqueness
            requirement is unmet.
    """
    if not specs:
        return pl.DataFrame(schema=METHOD_EXAMPLES_SCHEMA)

    annotated = annotate(df, alias_map=alias_map, verdicts=verdicts, sample=sample)
    curated = pl.DataFrame(
        {
            "slot": [spec.slot for spec in specs],
            "position": list(range(len(specs))),
            "comment_id": [spec.comment_id for spec in specs],
        },
        schema={"slot": pl.String, "position": pl.Int64, "comment_id": pl.String},
    )
    rows = curated.join(annotated, on="comment_id", how="left", maintain_order="left")

    missing = rows.filter(pl.col("body").is_null())
    for spec in missing.select("slot", "comment_id").iter_rows():
        raise MethodExamplesError(
            f"method_examples {spec[0]} {spec[1]}: not in the fact"
        )

    for slot, (requirement, predicate) in SLOT_CHECKS.items():
        failing = rows.filter((pl.col("slot") == slot) & ~predicate.fill_null(False))
        if failing.height:
            comment_id = failing.get_column("comment_id")[0]
            raise MethodExamplesError(
                f"method_examples {slot} {comment_id}: the slot requires {requirement}"
            )

    counts = dict(rows.group_by("slot").len().iter_rows())
    for slot, required in EXACT_SLOT_COUNTS.items():
        if counts.get(slot, 0) != required:
            raise MethodExamplesError(
                f"method_examples {slot}: {required} row(s) required, {counts.get(slot, 0)} curated"
            )
    if counts.get("read", 0) < 1:
        raise MethodExamplesError(
            "method_examples read: at least one row required, none curated"
        )

    case_rows = rows.filter(pl.col("slot") == "case")
    curated_cases = case_rows.get_column("attribution_case").to_list()
    required_cases = _required_cases(annotated)
    if sorted(curated_cases) != sorted(required_cases):
        raise MethodExamplesError(
            f"method_examples case: one row per branch the fact contains is required - "
            f"{', '.join(sorted(required_cases))}; curated {', '.join(sorted(curated_cases))}"
        )

    quiet = rows.filter(
        (pl.col("slot") == "slip")
        & (pl.col("label_sentiment") == QUIET_APPROVAL["label_sentiment"])
        & (pl.col("sentiment") == QUIET_APPROVAL["sentiment"])
    )
    if quiet.height == 0:
        raise MethodExamplesError(
            "method_examples slip: one quiet-approval row (manual positive, classifier "
            "neutral) is required"
        )

    out = rows.select(METHOD_EXAMPLES_SCHEMA.names())
    logger.info(
        f"method_examples: {out.height} rows - "
        + ", ".join(f"{slot} {counts.get(slot, 0)}" for slot in SLOTS)
    )
    return out


def scan_candidates(
    df: pl.DataFrame,
    *,
    alias_map: dict[str, str],
    verdicts: pl.DataFrame | None,
    sample: pl.DataFrame | None,
    per_slot: int = SCAN_PER_SLOT,
) -> dict[str, pl.DataFrame]:
    """
    The fact rows that would pass each slot's check, ranked for curation.

    Bodies at or under the receipts' length cap, highest score first;
    the case slot is grouped so every branch gets its own top rows. A
    ready-to-paste curation line comes with each row.

    Args:
        df: The usable fact with player_id attached.
        alias_map: Lowercase alias -> canonical name.
        verdicts: Resolved verdict sidecar, or None.
        sample: Accuracy sample, or None.
        per_slot: Rows kept per slot (per branch for the case slot).

    Returns:
        Slot -> candidate frame, in SLOTS order.
    """
    annotated = annotate(df, alias_map=alias_map, verdicts=verdicts, sample=sample)
    quotable = annotated.filter(
        pl.col("body").str.len_chars() <= COMMENT_SAMPLES_MAX_BODY_CHARS
    )
    columns = [
        "comment_id",
        "attribution_case",
        "mentioned_players",
        "sentiment_player",
        "attributed_player",
        "fan_team",
        "sentiment",
        "confidence",
        "target_raw",
        "verified_target",
        "label_sentiment",
        "label_target",
        "score",
        "body",
    ]
    report: dict[str, pl.DataFrame] = {}
    for slot, (_, predicate) in SLOT_CHECKS.items():
        passing = quotable.filter(predicate.fill_null(False)).sort(
            ["score", "comment_id"], descending=[True, False]
        )
        if slot == "case":
            passing = passing.filter(
                pl.col("comment_id").cum_count().over("attribution_case") <= per_slot
            ).sort(["attribution_case", "score"], descending=[False, True])
        else:
            passing = passing.head(per_slot)
        report[slot] = passing.select(columns).with_columns(
            pl.format(
                "- {slot: " + slot + ", comment_id: {}}", pl.col("comment_id")
            ).alias("curation")
        )
    return report
