"""
Download Reddit posts from Arctic Shift API.

This script downloads posts from r/nba for the 2024-25 NBA season.
Unlike download_comments.py, this script does not support resume - if interrupted,
delete the output file and restart.

Usage:
    # Download posts
    uv run python -m scripts.download_posts

    # Force restart (delete existing file)
    uv run python -m scripts.download_posts --force
"""

import argparse
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from pipeline.arctic_shift import ArcticShiftClient
from utils.constants import (
    PRIMARY_SUBREDDIT,
    RAW_DATA_SUBDIR,
    SEASON_END_DATE,
    SEASON_START_DATE,
)
from utils.formatting import format_duration

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
# Helper functions
# -----------------------------------------------------------------------------
def get_data_dir() -> Path:
    """
    Get the data directory from environment or use default.

    Returns:
        Path to data directory.
    """
    load_dotenv()
    data_dir = os.getenv("DATA_DIR", "./data")
    return Path(data_dir)


def date_to_epoch(date_str: str) -> int:
    """
    Convert ISO date string to Unix timestamp.

    Args:
        date_str: Date in YYYY-MM-DD format.

    Returns:
        Unix timestamp (seconds since epoch).
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return int(dt.timestamp())


# -----------------------------------------------------------------------------
# Download logic
# -----------------------------------------------------------------------------
def download_posts(
    client: ArcticShiftClient,
    output_path: Path,
    start_timestamp: int,
    end_timestamp: int,
) -> int:
    """
    Download all posts for r/nba within the date range.

    Uses ArcticShiftClient's generator-based API for memory-efficient
    streaming to disk.

    Args:
        client: ArcticShiftClient instance.
        output_path: Path to write JSONL file.
        start_timestamp: Start of date range (Unix timestamp).
        end_timestamp: End of date range (Unix timestamp).

    Returns:
        Total number of posts downloaded.
    """
    total_count = 0
    last_timestamp = start_timestamp

    with open(output_path, "w") as f:
        for post in client.fetch_posts(
            subreddit=PRIMARY_SUBREDDIT,
            after=start_timestamp,
            before=end_timestamp,
        ):
            f.write(json.dumps(post) + "\n")
            total_count += 1

            last_timestamp = post.get("created_utc", last_timestamp)

            # Progress logging every 1000 posts
            if total_count % 1000 == 0:
                logger.info(
                    f"  Progress: {total_count:,} posts "
                    f"(up to {datetime.fromtimestamp(last_timestamp).date()})"
                )

    return total_count


def main() -> None:
    """
    Main entry point - download r/nba posts.

    Flow:
        1. Parse CLI arguments
        2. Check for existing file (delete if --force)
        3. Download posts
        4. Print summary
    """
    parser = argparse.ArgumentParser(
        description="Download r/nba posts from Arctic Shift API"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing file and restart",
    )
    args = parser.parse_args()

    # Setup paths
    data_dir = get_data_dir()
    raw_dir = data_dir / RAW_DATA_SUBDIR
    raw_dir.mkdir(parents=True, exist_ok=True)

    output_path = raw_dir / f"r_{PRIMARY_SUBREDDIT}_posts.jsonl"

    # Handle existing file
    if output_path.exists():
        if args.force:
            output_path.unlink()
            logger.info(f"Deleted existing file: {output_path}")
        else:
            logger.error(
                f"Output file already exists: {output_path}\n"
                "Use --force to delete and restart."
            )
            return

    # Convert season dates to timestamps
    start_ts = date_to_epoch(SEASON_START_DATE)
    end_ts = date_to_epoch(SEASON_END_DATE)

    logger.info("=" * 60)
    logger.info("NBA Hate Tracker - Posts Download")
    logger.info("=" * 60)
    logger.info(f"Date range: {SEASON_START_DATE} to {SEASON_END_DATE}")
    logger.info(f"Subreddit: r/{PRIMARY_SUBREDDIT}")
    logger.info(f"Output: {output_path}")
    logger.info("=" * 60)

    start_time = time.time()

    with ArcticShiftClient() as client:
        count = download_posts(
            client=client,
            output_path=output_path,
            start_timestamp=start_ts,
            end_timestamp=end_ts,
        )

    elapsed = time.time() - start_time
    throughput = count / elapsed if elapsed > 0 else 0

    logger.info("=" * 60)
    logger.info("Download Complete!")
    logger.info("=" * 60)
    logger.info(
        f"Total: {count:,} posts in {format_duration(elapsed)} "
        f"({throughput:.1f} posts/sec)"
    )
    logger.info(f"Output: {output_path}")


if __name__ == "__main__":
    main()
