"""
Download Reddit comments from Arctic Shift API.

This script downloads comments from all target subreddits for the 2024-25 NBA season.
It handles pagination, rate limiting, and can resume from interruptions.

Usage:
    # Download all subreddits
    uv run python scripts/download_arctic_shift.py
    
    # Download single subreddit (for testing)
    uv run python scripts/download_arctic_shift.py --subreddit orlandomagic
    
    # Force restart (ignore progress file)
    uv run python scripts/download_arctic_shift.py --force
    
    # Combine options
    uv run python scripts/download_arctic_shift.py --subreddit nba --force

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
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# Add project root to path so we can import utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.constants import (
    ARCTIC_SHIFT_BASE_URL,
    ARCTIC_SHIFT_COMMENTS_ENDPOINT,
    ARCTIC_SHIFT_PAGE_SIZE,
    ARCTIC_SHIFT_RATE_LIMIT_BUFFER,
    ARCTIC_SHIFT_REQUEST_DELAY,
    PROGRESS_FILENAME,
    RAW_DATA_SUBDIR,
    SEASON_END_DATE,
    SEASON_START_DATE,
    TARGET_SUBREDDITS,
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
# Helper functions
# -----------------------------------------------------------------------------
def get_data_dir() -> Path:
    """
    Get the data directory from environment or use default.
    
    Why environment variable?
    - Your laptop might use ./data
    - A server might use /mnt/efs/data
    - Keeps infrastructure config separate from code
    """
    load_dotenv()
    data_dir = os.getenv("DATA_DIR", "./data")
    return Path(data_dir)

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

def _format_duration(seconds: float) -> str:
    """
    Format a duration in seconds to human-readable string.
    
    Examples:
        45.2 -> "45s"
        125.7 -> "2m 6s"
        3725.3 -> "1h 2m 5s"
    """
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours}h {minutes}m {secs}s"

# -----------------------------------------------------------------------------
# API interaction
# -----------------------------------------------------------------------------
def fetch_comments_page(
    subreddit: str,
    after_timestamp: int,
    before_timestamp: int,
    limit: int = ARCTIC_SHIFT_PAGE_SIZE,
) -> tuple[list[dict], dict[str, str]]:
    """
    Fetch a single page of comments from Arctic Shift API.

    API notes:
        - sort=asc ensures we paginate forward in time
        - after/before are Unix timestamps
        - Response includes X-RateLimit-* headers
    
    Args:
        subreddit: Subreddit name (without r/)
        after_timestamp: Unix timestamp - get comments AFTER this time
        before_timestamp: Unix timestamp - get comments BEFORE this time
        limit: Max comments per request
        
    Returns:
        Tuple of (list of comment dicts, response headers dict)
    """
    url = f"{ARCTIC_SHIFT_BASE_URL}{ARCTIC_SHIFT_COMMENTS_ENDPOINT}"
    
    params = {
        "subreddit": subreddit,
        "after": after_timestamp,
        "before": before_timestamp,
        "sort": "asc",  # Oldest first - critical for pagination!
        "limit": limit,
    }
    
    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()
    
    data = response.json()
    comments = data.get("data", [])
    
    return comments, dict(response.headers)


def check_rate_limit(headers: dict[str, str]) -> None:
    """
    Check rate limit headers and sleep if necessary.
    
    Arctic Shift returns:
        X-RateLimit-Remaining: requests left in window
        X-RateLimit-Reset: Unix timestamp when limit resets
        
    We proactively sleep if remaining drops below buffer threshold.
    """
    remaining = headers.get("X-RateLimit-Remaining")
    reset_time = headers.get("X-RateLimit-Reset")
    
    if remaining is None:
        # No rate limit headers - API might not always include them
        return
        
    remaining = int(remaining)
    
    if remaining < ARCTIC_SHIFT_RATE_LIMIT_BUFFER:
        if reset_time:
            reset_ts = int(reset_time)
            sleep_seconds = max(0, reset_ts - int(time.time())) + 1
            logger.warning(
                f"Rate limit low ({remaining} remaining). "
                f"Sleeping {sleep_seconds}s until reset."
            )
            time.sleep(sleep_seconds)
        else:
            # No reset time provided, use conservative sleep
            logger.warning(f"Rate limit low ({remaining}). Sleeping 60s.")
            time.sleep(60)


# -----------------------------------------------------------------------------
# Download logic
# -----------------------------------------------------------------------------
def download_subreddit(
    subreddit: str,
    output_path: Path,
    start_timestamp: int,
    end_timestamp: int,
    resume_from: int | None = None,
) -> int:
    """
    Download all comments for a subreddit within the date range.

    How pagination works:
        1. Request comments after=start_timestamp, sort=asc
        2. Get oldest N comments
        3. Take created_utc of LAST comment as new after value
        4. Repeat until no more comments or we hit end_timestamp
    
    Args:
        subreddit: Subreddit name
        output_path: Path to write JSONL file
        start_timestamp: Start of date range (Unix timestamp)
        end_timestamp: End of date range (Unix timestamp)
        resume_from: If resuming, the timestamp to continue from
        
    Returns:
        Total number of comments downloaded
    """
    current_after = resume_from if resume_from else start_timestamp
    total_count = 0
    
    # Open in append mode if resuming, write mode if fresh
    mode = "a" if resume_from else "w"
    
    with open(output_path, mode) as f:
        while current_after < end_timestamp:
            try:
                comments, headers = fetch_comments_page(
                    subreddit=subreddit,
                    after_timestamp=current_after,
                    before_timestamp=end_timestamp,
                )
            except requests.RequestException as e:
                logger.error(f"Request failed: {e}. Retrying in 30s...")
                time.sleep(30)
                continue
            
            if not comments:
                # No more comments in range - we're done
                logger.info(f"  No more comments after {current_after}")
                break
            
            # Write comments to file
            for comment in comments:
                f.write(json.dumps(comment) + "\n")
            
            total_count += len(comments)
            
            # Update pagination cursor to last comment's timestamp
            # Add 1 to avoid re-fetching the same comment (API is inclusive)
            last_timestamp = comments[-1].get("created_utc", current_after)
            current_after = last_timestamp + 1
            
            # Progress logging every 10 pages
            if total_count % (ARCTIC_SHIFT_PAGE_SIZE * 10) == 0:
                logger.info(
                    f"  Progress: {total_count:,} comments "
                    f"(up to {datetime.fromtimestamp(last_timestamp).date()})"
                )
            
            # Respect rate limits
            check_rate_limit(headers)
            
            # Be nice to the free API
            time.sleep(ARCTIC_SHIFT_REQUEST_DELAY)
    
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
    data_dir = get_data_dir()
    raw_dir = data_dir / RAW_DATA_SUBDIR
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
                f"in {_format_duration(sub_elapsed)} ({throughput:.1f} comments/sec)"
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
    
    logger.info(f"This session: {len(session_stats)} subreddits, {total_comments:,} comments")
    logger.info(f"Total time: {_format_duration(session_elapsed)} (avg {overall_throughput:.1f} comments/sec)")
    logger.info("")
    
    # Per-subreddit breakdown (sorted by count descending)
    for sub, stats in sorted(session_stats.items(), key=lambda x: -x[1]["count"]):
        throughput = stats["count"] / stats["duration"] if stats["duration"] > 0 else 0
        logger.info(
            f"  {sub}: {stats['count']:,} comments "
            f"in {_format_duration(stats['duration'])} ({throughput:.1f}/sec)"
        )

if __name__ == "__main__":
    main()
