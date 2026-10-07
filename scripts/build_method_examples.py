"""
Curation tools for the method examples: the candidate scan and an in-memory dry run.

The table itself is built and written by scripts.aggregate_sentiment,
the one writer of the manifest. This script serves curation: --scan
writes, per slot, the fact rows that would pass that slot's check,
ranked by score, under reference/ (never published), with the season's
count per attribution case; --dry-run builds the curated table in
memory and reports each row, writing nothing. Both read the fact, the
verifier sidecar and the accuracy sample where they exist, and the
Player dimension an aggregate run produced.

Usage:
    uv run python -m scripts.build_method_examples --season 2025-26 --scan
    uv run python -m scripts.build_method_examples --season 2025-26 --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

import polars as pl

from pipeline.accuracy import SAMPLE_FILENAME, read_accuracy_sample
from pipeline.aggregation import (
    attach_player_id,
    load_attributed_frame,
    read_classifier_stamps,
)
from pipeline.method_examples import (
    MethodExamplesError,
    attribution_cases,
    build_method_examples,
    count_attribution_cases,
    scan_candidates,
)
from pipeline.receipts import load_target_verdicts, resolve_verdicts
from utils.constants import METHOD_EXAMPLE_CANDIDATES_FILENAME
from utils.method_examples_config import load_method_examples_config
from utils.paths import get_dashboard_dir, get_processed_dir, get_reference_dir
from utils.player_config import build_alias_to_player_map
from utils.season_config import get_active_season, set_season_override

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

FACT_FILENAME = "sentiment.parquet"
TARGETS_FILENAME = "sentiment_targets.parquet"
PLAYERS_FILENAME = "players.parquet"


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def load_inputs(
    fact_path: Path, players_path: Path, targets_path: Path, accuracy_path: Path
) -> tuple[pl.DataFrame, dict[str, str], pl.DataFrame | None, pl.DataFrame | None]:
    """
    Read what the slots are judged on: the usable fact with ids, the sidecar, the sample.

    Args:
        fact_path: Path to sentiment.parquet.
        players_path: Path to the Player dimension.
        targets_path: Path to sentiment_targets.parquet; absent means no verdicts.
        accuracy_path: Path to accuracy_sample.parquet; absent means no labels.

    Returns:
        Tuple of (fact with player_id, alias map, resolved verdicts or
        None, sample or None).

    Raises:
        FileNotFoundError: If the Player dimension is missing; the
            aggregate has not run for the season.
    """
    df, _ = load_attributed_frame(fact_path)
    df = attach_player_id(df, pl.read_parquet(players_path))
    alias_map = build_alias_to_player_map()
    verdicts = None
    if targets_path.exists():
        raw, _ = load_target_verdicts(targets_path)
        verdicts = resolve_verdicts(raw, alias_map)
    read = read_accuracy_sample(accuracy_path, read_classifier_stamps(fact_path))
    sample = read[0] if read is not None else None
    return df, alias_map, verdicts, sample


def main() -> None:
    """Main entry point for the method-example curation tools."""
    parser = argparse.ArgumentParser(
        description="Method-example curation: the candidate scan or an in-memory dry run"
    )
    parser.add_argument(
        "--season",
        default=None,
        metavar="YYYY-YY",
        help='Override the active season (e.g. "2024-25"); every path resolves '
        "to it for this run",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--scan",
        action="store_true",
        help="Report the rows that fit each slot, and the count per attribution "
        "case, under reference/",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the curated table in memory and report each row; write nothing",
    )
    args = parser.parse_args()

    if args.season:
        set_season_override(args.season)

    season = get_active_season()
    fact_path = get_processed_dir() / FACT_FILENAME
    targets_path = get_processed_dir() / TARGETS_FILENAME
    accuracy_path = get_reference_dir() / SAMPLE_FILENAME
    players_path = get_dashboard_dir() / PLAYERS_FILENAME
    if not fact_path.exists():
        logger.error(f"{fact_path} not found")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info(f"Method examples: {season} ({'scan' if args.scan else 'dry run'})")
    logger.info(f"  fact:     {fact_path}")
    logger.info(f"  verdicts: {targets_path}")
    logger.info(f"  sample:   {accuracy_path}")
    logger.info("=" * 60)

    try:
        df, alias_map, verdicts, sample = load_inputs(
            fact_path, players_path, targets_path, accuracy_path
        )
    except FileNotFoundError as e:
        logger.error(f"{e.filename} not found - run scripts.aggregate_sentiment first")
        sys.exit(1)

    if args.scan:
        _scan(df, alias_map, verdicts, sample)
    else:
        _dry_run(df, alias_map, verdicts, sample)


def _scan(
    df: pl.DataFrame,
    alias_map: dict[str, str],
    verdicts: pl.DataFrame | None,
    sample: pl.DataFrame | None,
) -> None:
    """Write one candidate report per slot; log the count per attribution case."""
    counts = count_attribution_cases(attribution_cases(df, alias_map))
    logger.info("Rows per attribution case:")
    for case, rows in counts.iter_rows():
        logger.info(f"  {case:<28} {rows:>10,}")

    report = scan_candidates(df, alias_map=alias_map, verdicts=verdicts, sample=sample)
    logger.info("=" * 60)
    for slot, candidates in report.items():
        out = get_reference_dir() / METHOD_EXAMPLE_CANDIDATES_FILENAME.format(slot=slot)
        candidates.with_columns(pl.col("mentioned_players").list.join(" | ")).write_csv(
            out
        )
        logger.info(f"Wrote {out}: {candidates.height} candidates")
    logger.info("=" * 60)


def _dry_run(
    df: pl.DataFrame,
    alias_map: dict[str, str],
    verdicts: pl.DataFrame | None,
    sample: pl.DataFrame | None,
) -> None:
    """Build the curated table in memory and report each row; write nothing."""
    try:
        table = build_method_examples(
            df,
            load_method_examples_config(),
            alias_map=alias_map,
            verdicts=verdicts,
            sample=sample,
        )
    except MethodExamplesError as e:
        logger.error(e)
        sys.exit(1)
    logger.info("=" * 60)
    for row in table.rows(named=True):
        logger.info(
            f"  {row['position']:>2} {row['slot']:<12} {row['comment_id']:<8} "
            f"{row['attribution_case']:<26} {row['sentiment']} "
            f"{row['confidence']:.2f}  {row['attributed_player'] or '-'}"
        )
    logger.info(f"Dry run - {table.height} examples built, nothing written")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
