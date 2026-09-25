"""
Read the labeled accuracy workbook back and write the sample parquet.

Refuses an incomplete or off-list workbook, naming the rows. Otherwise
writes data/<season>/reference/accuracy_sample.parquet, stamped with
the draw's config and classifier identity, and logs the figures the
next aggregation will publish.

Usage:
    uv run python -m scripts.import_accuracy_sample
    uv run python -m scripts.import_accuracy_sample --season 2024-25

Input:  data/<season>/reference/accuracy_sample.xlsx
Output: data/<season>/reference/accuracy_sample.parquet
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from pipeline.accuracy import (
    SAMPLE_FILENAME,
    WORKBOOK_FILENAME,
    log_figures,
    read_workbook,
    score_sample,
)
from pipeline.schemas import SCHEMA_VERSION
from utils.paths import get_reference_dir
from utils.season_config import set_season_override

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Main entry point with CLI argument handling."""
    parser = argparse.ArgumentParser(
        description="Read the labeled accuracy workbook and write the sample parquet"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="The labeled workbook "
        f"(default: data/<season>/reference/{WORKBOOK_FILENAME})",
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

    workbook_path = args.input or get_reference_dir() / WORKBOOK_FILENAME
    output_path = get_reference_dir() / SAMPLE_FILENAME

    if not workbook_path.exists():
        logger.error(f"Workbook not found: {workbook_path}")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Import Accuracy Sample")
    logger.info("=" * 60)
    logger.info(f"Workbook: {workbook_path}")
    logger.info(f"Output:   {output_path}")
    logger.info("=" * 60)

    try:
        sample, stamps = read_workbook(workbook_path)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # The draw's stamps carry forward, not the live versions: the target
    # options were offered under the config the draw was made with
    sample.write_parquet(
        output_path,
        metadata={
            "schema_version": str(SCHEMA_VERSION),
            **stamps,
            "labeled_at": datetime.now(UTC).date().isoformat(),
        },
    )
    logger.info(f"Wrote {sample.height:,} rows to {output_path}")

    seed = stamps.get("sample_seed")
    log_figures(
        score_sample(
            sample,
            seed=int(seed) if seed is not None else None,
            drawn_at=stamps.get("drawn_at"),
        )
    )


if __name__ == "__main__":
    main()
