"""
Build the corpus_daily snapshot: the funnel's counts per UTC day.

Streams the raw comments download and the filtered mentions file for
their created_utc, counts the fact's usable and attributed rows, and
writes the zero-filled day grid to the season's reference directory,
where aggregation exports it. The owned columns are checked against
season.yaml's corpus record before the snapshot is written.

Usage:
    uv run python -m scripts.build_corpus_daily
    uv run python -m scripts.build_corpus_daily --season 2024-25
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from pipeline.corpus import (
    CORPUS_DAILY_FILENAME,
    FILTERED_COMMENTS_FILENAME,
    RAW_COMMENTS_FILENAME,
    build_corpus_daily,
    check_corpus_totals,
    count_fact_by_day,
    count_ndjson_by_day,
)
from pipeline.lineage import config_stamps
from pipeline.schemas import CORPUS_DAILY_SCHEMA, SCHEMA_VERSION, validate_schema
from utils.paths import (
    get_filtered_dir,
    get_processed_dir,
    get_raw_dir,
    get_reference_dir,
)
from utils.season_config import (
    get_active_season,
    load_season_config,
    set_season_override,
)

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SENTIMENT_FILENAME = "sentiment.parquet"


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for building the corpus_daily snapshot."""
    parser = argparse.ArgumentParser(
        description="Build corpus_daily (the funnel per UTC day) from the raw download"
    )
    parser.add_argument(
        "--season",
        default=None,
        metavar="YYYY-YY",
        help='Override the active season (e.g. "2024-25"); the input and '
        "output paths both resolve to it for this run",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing snapshot",
    )
    args = parser.parse_args()

    if args.season:
        set_season_override(args.season)

    season = get_active_season()
    raw_path = get_raw_dir() / RAW_COMMENTS_FILENAME
    filtered_path = get_filtered_dir() / FILTERED_COMMENTS_FILENAME
    fact_path = get_processed_dir() / SENTIMENT_FILENAME
    output_path = get_reference_dir() / CORPUS_DAILY_FILENAME

    for path, producer in (
        (raw_path, "scripts.download_comments"),
        (filtered_path, "scripts.filter_comments"),
        (fact_path, "scripts.collect_results"),
    ):
        if not path.exists():
            logger.error(f"{path} not found - run {producer} first")
            sys.exit(1)
    if output_path.exists() and not args.force:
        logger.error(
            f"{output_path} already exists - move it aside to archive it, "
            "or pass --force to overwrite"
        )
        sys.exit(1)

    logger.info("=" * 60)
    logger.info(f"corpus_daily: {season}")
    logger.info("=" * 60)

    corpus_daily = build_corpus_daily(
        count_ndjson_by_day(raw_path, "raw_comments"),
        count_ndjson_by_day(filtered_path, "population_submitted"),
        count_fact_by_day(fact_path),
    )
    validate_schema(corpus_daily, CORPUS_DAILY_SCHEMA, CORPUS_DAILY_FILENAME)
    check_corpus_totals(corpus_daily, load_season_config()["corpus"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    corpus_daily.write_parquet(
        output_path,
        metadata={
            "season": season,
            "processed_at": datetime.now(timezone.utc).date().isoformat(),
            **config_stamps("corpus_daily"),
            "schema_version": str(SCHEMA_VERSION),
        },
    )
    logger.info(
        f"Wrote {corpus_daily.height} days to {output_path} "
        f"({corpus_daily['day'].min()} to {corpus_daily['day'].max()})"
    )
    for column in CORPUS_DAILY_SCHEMA.names()[1:]:
        series = corpus_daily[column]
        total = (
            "unknown" if series.null_count() == series.len() else f"{series.sum():,}"
        )
        logger.info(f"  {column:<22} {total:>12}")


if __name__ == "__main__":
    main()
