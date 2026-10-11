"""
Build the download_daily snapshot: the download's counts per Eastern game night.

Streams the raw comments download and the filtered mentions file for
their created_utc and writes the zero-filled day grid to the season's
reference directory, where aggregation joins the fact's columns on to
make corpus_daily. The owned columns are checked against season.yaml's
corpus record before the snapshot is written.

Usage:
    uv run python -m scripts.build_download_daily
    uv run python -m scripts.build_download_daily --season 2024-25
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from pipeline.corpus import (
    DOWNLOAD_DAILY_FILENAME,
    FILTERED_COMMENTS_FILENAME,
    RAW_COMMENTS_FILENAME,
    build_download_daily,
    check_corpus_totals,
    count_ndjson_by_day,
)
from pipeline.lineage import config_stamps
from pipeline.schemas import DOWNLOAD_DAILY_SCHEMA, SCHEMA_VERSION, validate_schema
from utils.paths import get_filtered_dir, get_raw_dir, get_reference_dir
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


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for building the download_daily snapshot."""
    parser = argparse.ArgumentParser(
        description="Build download_daily (the download per game night) from the raw files"
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
    output_path = get_reference_dir() / DOWNLOAD_DAILY_FILENAME

    for path, producer in (
        (raw_path, "scripts.download_comments"),
        (filtered_path, "scripts.filter_comments"),
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
    logger.info(f"download_daily: {season}")
    logger.info("=" * 60)

    download_daily = build_download_daily(
        count_ndjson_by_day(raw_path, "raw_comments"),
        count_ndjson_by_day(filtered_path, "population_submitted"),
    )
    validate_schema(download_daily, DOWNLOAD_DAILY_SCHEMA, DOWNLOAD_DAILY_FILENAME)
    check_corpus_totals(download_daily, load_season_config()["corpus"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    download_daily.write_parquet(
        output_path,
        metadata={
            "season": season,
            "processed_at": datetime.now(timezone.utc).date().isoformat(),
            **config_stamps("download_daily"),
            "schema_version": str(SCHEMA_VERSION),
        },
    )
    logger.info(
        f"Wrote {download_daily.height} days to {output_path} "
        f"({download_daily['day'].min()} to {download_daily['day'].max()})"
    )
    for column in DOWNLOAD_DAILY_SCHEMA.names()[1:]:
        logger.info(f"  {column:<22} {download_daily[column].sum():>12,}")


if __name__ == "__main__":
    main()
