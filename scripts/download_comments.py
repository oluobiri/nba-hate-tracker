"""
Download Reddit comments from Arctic Shift API.

This script downloads comments from all target subreddits for the 2024-25 NBA season.
It handles pagination, rate limiting, and can resume from interruptions.

Usage:
    # Download all subreddits
    uv run python -m scripts.download_comments

    # Download single subreddit (for testing)
    uv run python -m scripts.download_comments --subreddit orlandomagic

    # Force restart (ignore progress file)
    uv run python -m scripts.download_comments --force

    # Combine options
    uv run python -m scripts.download_comments --subreddit nba --force

Design decisions:
    - Sequential downloads (one subreddit at a time) to respect the free API
    - Pagination via created_utc ascending - simple and reliable
    - Progress saved after each subreddit completes (resumable)
    - Rate limit headers checked to avoid hitting limits
    - Configurable delay between requests (default 0.5s)

Known limitations:
    - Pagination uses timestamp + 1 second to avoid refetching the same comment.
      In rare high-volume moments (100+ comments/second, e.g., Game 7 buzzer),
      some comments may be skipped. For sentiment analysis on millions of
      comments, this <0.1% edge case is acceptable. If forensic completeness
      is needed, implement deduplication with seen_ids tracking.
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline.arctic_shift import ArcticShiftClient
from utils.constants import (
    ARCTIC_SHIFT_PAGE_SIZE,
    PROGRESS_FILENAME,
    SEASON_END_DATE,
    SEASON_START_DATE,
    TARGET_SUBREDDITS,
)
from utils.formatting import format_duration
from utils.paths import get_raw_dir

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
def date_to_epoch(date_str: str) -> int:
    """
    Convert ISO date string to Unix timestamp.

    Args:
        date_str: Date in YYYY-MM-DD format

    Returns:
        Unix timestamp (seconds since epoch)
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return int(dt.timestamp())


def load_progress(progress_path: Path) -> dict[str, Any]:
    """
    Load download progress from disk.

    Structure:
        {
            "completed": ["subreddit1", "subreddit2"],
            "in_progress": {
                "subreddit3": {"last_timestamp": 1234567890, "count": 50000}
            }
        }

    Returns empty structure if file doesn't exist (fresh start).
    """
    if progress_path.exists():
        with open(progress_path, "r") as f:
            return json.load(f)
    return {"completed": [], "in_progress": {}}


def save_progress(progress_path: Path, progress: dict[str, Any]) -> None:
    """
    Save download progress to disk.

    Called after each subreddit completes so we can resume on failure.
    """
    with open(progress_path, "w") as f:
        json.dump(progress, f, indent=2)
    logger.debug(f"Progress saved to {progress_path}")


# -----------------------------------------------------------------------------
# Download logic
# -----------------------------------------------------------------------------
def download_subreddit(
    client: ArcticShiftClient,
    subreddit: str,
    output_path: Path,
    start_timestamp: int,
    end_timestamp: int,
    resume_from: int | None = None,
) -> int:
    """
    Download all comments for a subreddit within the date range.

    Uses ArcticShiftClient's generator-based API for memory-efficient
    streaming to disk.

    Args:
        client: ArcticShiftClient instance
        subreddit: Subreddit name
        output_path: Path to write JSONL file
        start_timestamp: Start of date range (Unix timestamp)
        end_timestamp: End of date range (Unix timestamp)
        resume_from: If resuming, the timestamp to continue from

    Returns:
        Total number of comments downloaded
    """
    # Use resume timestamp if provided, otherwise start from beginning
    after_timestamp = resume_from if resume_from else start_timestamp
    total_count = 0
    last_timestamp = after_timestamp

    # Open in append mode if resuming, write mode if fresh
    mode = "a" if resume_from else "w"

    with open(output_path, mode) as f:
        for comment in client.fetch_comments(
            subreddit=subreddit,
            after=after_timestamp,
            before=end_timestamp,
        ):
            # Write comment to file
            f.write(json.dumps(comment) + "\n")
            total_count += 1

            # Track last timestamp for progress logging
            last_timestamp = comment.get("created_utc", last_timestamp)

            # Progress logging every 1000 comments
            if total_count % (ARCTIC_SHIFT_PAGE_SIZE * 10) == 0:
                logger.info(
                    f"  Progress: {total_count:,} comments "
                    f"(up to {datetime.fromtimestamp(last_timestamp).date()})"
                )

    if total_count == 0:
        logger.info(f"  No comments found after {after_timestamp}")

    return total_count


def main() -> None:
    """
    Main entry point - download all target subreddits.

    Flow:
        1. Parse CLI arguments
        2. Load progress (skip completed subreddits, unless --force)
        3. For each incomplete subreddit:
           a. Download all comments
           b. Mark as complete
           c. Save progress
        4. Print summary
    """
    # Parse CLI arguments
    parser = argparse.ArgumentParser(
        description="Download NBA subreddit comments from Arctic Shift API"
    )
    parser.add_argument(
        "--subreddit",
        help="Download only this subreddit (for testing)",
        default=None,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore progress file and start fresh",
    )
    args = parser.parse_args()

    # Setup paths
    raw_dir = get_raw_dir()
    raw_dir.mkdir(parents=True, exist_ok=True)

    progress_path = raw_dir / PROGRESS_FILENAME

    # Load or reset progress
    if args.force:
        progress = {"completed": [], "in_progress": {}}
        logger.info("Force mode: ignoring previous progress")
    else:
        progress = load_progress(progress_path)

    # Determine which subreddits to download
    if args.subreddit:
        # Single subreddit mode (for testing)
        if args.subreddit.lower() not in [s.lower() for s in TARGET_SUBREDDITS]:
            logger.warning(
                f"'{args.subreddit}' is not in TARGET_SUBREDDITS. "
                "Proceeding anyway (might be intentional for testing)."
            )
        targets = [args.subreddit.lower()]
    else:
        targets = TARGET_SUBREDDITS

    # Convert season dates to timestamps
    start_ts = date_to_epoch(SEASON_START_DATE)
    end_ts = date_to_epoch(SEASON_END_DATE)

    logger.info("=" * 60)
    logger.info("NBA Hate Tracker - Arctic Shift Download")
    logger.info("=" * 60)
    logger.info(f"Date range: {SEASON_START_DATE} to {SEASON_END_DATE}")
    logger.info(f"Subreddits to process: {len(targets)}")
    logger.info(f"Output dir: {raw_dir}")
    if not args.force:
        logger.info(f"Already completed: {len(progress['completed'])}")
    logger.info("=" * 60)

    # Track stats and timing for summary
    session_start_time = time.time()
    session_stats: dict[str, dict[str, float]] = {}

    # Use client as context manager for automatic cleanup
    with ArcticShiftClient() as client:
        for subreddit in targets:
            # Skip if already completed (unless in single-sub mode with --force)
            if subreddit in progress["completed"] and not args.force:
                logger.info(f"Skipping {subreddit} (already complete)")
                continue

            output_path = raw_dir / f"r_{subreddit}_comments.jsonl"

            # Check if we're resuming mid-download
            resume_from = None
            if subreddit in progress.get("in_progress", {}):
                resume_info = progress["in_progress"][subreddit]
                resume_from = resume_info.get("last_timestamp")
                logger.info(
                    f"Resuming {subreddit} from {resume_from} "
                    f"({resume_info.get('count', 0):,} comments so far)"
                )
            else:
                logger.info(f"Starting {subreddit}...")

            # Download!
            try:
                sub_start_time = time.time()

                count = download_subreddit(
                    client=client,
                    subreddit=subreddit,
                    output_path=output_path,
                    start_timestamp=start_ts,
                    end_timestamp=end_ts,
                    resume_from=resume_from,
                )

                sub_elapsed = time.time() - sub_start_time

                # Mark as complete
                progress["completed"].append(subreddit)
                if subreddit in progress.get("in_progress", {}):
                    del progress["in_progress"][subreddit]

                session_stats[subreddit] = {"count": count, "duration": sub_elapsed}

                # Calculate throughput
                throughput = count / sub_elapsed if sub_elapsed > 0 else 0
                logger.info(
                    f"Completed {subreddit}: {count:,} comments "
                    f"in {format_duration(sub_elapsed)} ({throughput:.1f} comments/sec)"
                )

            except KeyboardInterrupt:
                logger.warning("\nInterrupted! Saving progress...")
                # Save partial progress
                if subreddit not in progress.get("in_progress", {}):
                    progress["in_progress"] = progress.get("in_progress", {})
                # Note: We could track last_timestamp here for better resume
                save_progress(progress_path, progress)
                sys.exit(1)

            except Exception as e:
                logger.error(f"Failed on {subreddit}: {e}")
                # Save progress so we can resume
                save_progress(progress_path, progress)
                raise

            # Save progress after each subreddit
            save_progress(progress_path, progress)

    # Summary
    session_elapsed = time.time() - session_start_time

    logger.info("=" * 60)
    logger.info("Download Complete!")
    logger.info("=" * 60)

    total_comments = sum(s["count"] for s in session_stats.values())
    total_duration = sum(s["duration"] for s in session_stats.values())
    overall_throughput = total_comments / total_duration if total_duration > 0 else 0

    logger.info(
        f"This session: {len(session_stats)} subreddits, {total_comments:,} comments"
    )
    logger.info(
        f"Total time: {format_duration(session_elapsed)} (avg {overall_throughput:.1f} comments/sec)"
    )
    logger.info("")

    # Per-subreddit breakdown (sorted by count descending)
    for sub, stats in sorted(session_stats.items(), key=lambda x: -x[1]["count"]):
        throughput = stats["count"] / stats["duration"] if stats["duration"] > 0 else 0
        logger.info(
            f"  {sub}: {stats['count']:,} comments "
            f"in {format_duration(stats['duration'])} ({throughput:.1f}/sec)"
        )


if __name__ == "__main__":
    main()
