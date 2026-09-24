"""
Draw the accuracy sample and write its labeling workbook.

Reads the season's sentiment.parquet, draws n attributed rows uniformly
at random under a seed, and writes data/<season>/reference/
accuracy_sample.xlsx: the comments with list-validated verdict columns
and no prediction in sight. Fill it in, then import_accuracy_sample.

Usage:
    uv run python -m scripts.export_accuracy_sample
    uv run python -m scripts.export_accuracy_sample --season 2024-25 --n 500

Input:
    - data/<season>/processed/sentiment.parquet
    - data/<season>/reference/posts_bridge.parquet (titles; optional)
Output: data/<season>/reference/accuracy_sample.xlsx
"""

import argparse
import logging
import sys
from datetime import UTC, datetime

import polars as pl

from pipeline.accuracy import WORKBOOK_FILENAME, draw_sample, write_workbook
from pipeline.aggregation import load_attributed_frame, read_classifier_stamps
from pipeline.lineage import config_stamps
from pipeline.posts import POSTS_BRIDGE_FILENAME
from utils.constants import ACCURACY_SAMPLE_N, ACCURACY_SAMPLE_SEED
from utils.paths import get_processed_dir, get_reference_dir
from utils.season_config import set_season_override

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SENTIMENT_FILENAME = "sentiment.parquet"


def main() -> None:
    """Main entry point with CLI argument handling."""
    parser = argparse.ArgumentParser(
        description="Draw the accuracy sample and write its labeling workbook"
    )
    parser.add_argument(
        "--n",
        type=int,
        default=ACCURACY_SAMPLE_N,
        help=f"Rows to draw (default: {ACCURACY_SAMPLE_N})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=ACCURACY_SAMPLE_SEED,
        help=f"Sampling seed (default: {ACCURACY_SAMPLE_SEED})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing workbook (its verdicts are lost)",
    )
    parser.add_argument(
        "--season",
        default=None,
        metavar="YYYY-YY",
        help='Override the active season (e.g. "2024-25"); data paths and '
        "player config resolve to it for this run",
    )
    args = parser.parse_args()

    if args.season:
        set_season_override(args.season)

    input_path = get_processed_dir() / SENTIMENT_FILENAME
    bridge_path = get_reference_dir() / POSTS_BRIDGE_FILENAME
    workbook_path = get_reference_dir() / WORKBOOK_FILENAME

    if not input_path.exists():
        logger.error(f"Sentiment parquet not found: {input_path}")
        sys.exit(1)
    if workbook_path.exists() and not args.force:
        logger.error(
            f"{workbook_path} already exists; it may hold verdicts. "
            f"Pass --force to draw over it"
        )
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Export Accuracy Sample")
    logger.info("=" * 60)
    logger.info(f"Input:    {input_path}")
    logger.info(f"Bridge:   {bridge_path}")
    logger.info(f"Workbook: {workbook_path}")
    logger.info(f"n={args.n}, seed={args.seed}")
    logger.info("=" * 60)

    df, _ = load_attributed_frame(input_path)
    posts = None
    if bridge_path.exists():
        posts = pl.read_parquet(bridge_path, columns=["post_id", "title"])
    else:
        logger.warning(f"{bridge_path} not found: rows will carry no post title")
    sample = draw_sample(df, posts, n=args.n, seed=args.seed)

    # The draw's birth certificate rides in the workbook so the import
    # can stamp the parquet without the fact. The target lists are the
    # fact's mentions, so the fact's players stamp carries forward, not
    # the live version
    fact_metadata = pl.read_parquet_metadata(input_path)
    stamps = {
        **{
            key: fact_metadata[key]
            for key in config_stamps("accuracy_sample")
            if key in fact_metadata
        },
        **{
            key: value
            for key, value in read_classifier_stamps(input_path).items()
            if value is not None
        },
        "sample_seed": str(args.seed),
        "sample_n": str(args.n),
        "drawn_at": datetime.now(UTC).date().isoformat(),
    }
    workbook_path.parent.mkdir(parents=True, exist_ok=True)
    write_workbook(sample, workbook_path, stamps)
    logger.info(f"Wrote {sample.height:,} rows to {workbook_path}")


if __name__ == "__main__":
    main()
