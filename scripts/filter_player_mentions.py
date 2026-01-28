"""
Filter comments to those mentioning tracked NBA players.

Streams through cleaned JSONL, finds player mentions, and outputs
only comments that mention at least one tracked player.

Usage:
    # Run with defaults (recommended)
    uv run python -m scripts.filter_player_mentions

    # Explicit paths
    uv run python -m scripts.filter_player_mentions data/filtered/r_nba_cleaned.jsonl data/filtered/r_nba_player_mentions.jsonl

    # Preview first 1K lines (for testing)
    uv run python -m scripts.filter_player_mentions --limit 1000

Input: Cleaned JSONL from clean_raw_comments.py
Output: JSONL with only player-mentioning comments, plus mentioned_players field
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from tqdm import tqdm

from pipeline.processors import filter_player_mentions
from utils.formatting import format_duration, format_size

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
# Default paths
# -----------------------------------------------------------------------------

DEFAULT_INPUT = Path("data/filtered/r_nba_cleaned.jsonl")
DEFAULT_OUTPUT = Path("data/filtered/r_nba_player_mentions.jsonl")


# -----------------------------------------------------------------------------
# Core processing
# -----------------------------------------------------------------------------


def count_lines(filepath: Path) -> int:
    """
    Count lines in a file for progress bar total.

    Args:
        filepath: Path to the file to count.

    Returns:
        Number of lines in the file.
    """
    logger.info(f"Counting lines in {filepath.name}...")
    count = 0
    with open(filepath) as f:
        for _ in f:
            count += 1
    return count


def process_file(
    input_path: Path,
    output_path: Path,
    limit: int | None = None,
    skip_line_count: bool = False,
) -> tuple[dict[str, int], float]:
    """
    Stream process a JSONL file, filtering for player mentions.

    Args:
        input_path: Path to input JSONL file.
        output_path: Path to write filtered JSONL.
        limit: Optional max lines to process (for testing).
        skip_line_count: Skip counting lines (faster start, no progress %).

    Returns:
        Tuple of (stats dict, elapsed_seconds).
    """
    stats = {
        "total": 0,
        "accepted": 0,
        "rejected": 0,
        "malformed": 0,
    }

    # Get total for progress bar (unless skipped or limited)
    if limit:
        total = limit
    elif skip_line_count:
        total = None
    else:
        total = count_lines(input_path)

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Processing {input_path.name}...")

    start_time = time.time()

    with open(input_path) as f_in, open(output_path, "w") as f_out:
        lines = tqdm(f_in, total=total, desc="Filtering", unit=" lines")

        for i, line in enumerate(lines):
            if limit and i >= limit:
                break

            line = line.strip()
            if not line:
                continue

            stats["total"] += 1

            # Parse JSON
            try:
                comment = json.loads(line)
            except json.JSONDecodeError:
                stats["malformed"] += 1
                continue

            # Filter for player mentions
            result = filter_player_mentions(comment)

            if result is None:
                stats["rejected"] += 1
            else:
                stats["accepted"] += 1
                f_out.write(json.dumps(result) + "\n")

    elapsed = time.time() - start_time
    return stats, elapsed


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point with CLI argument handling."""
    parser = argparse.ArgumentParser(
        description="Filter comments to those mentioning tracked NBA players"
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=DEFAULT_INPUT,
        help=f"Path to input JSONL file (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=DEFAULT_OUTPUT,
        help=f"Path to write filtered JSONL output (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only first N lines (for testing)",
    )
    parser.add_argument(
        "--skip-line-count",
        action="store_true",
        help="Skip counting lines (faster start, but no progress percentage)",
    )
    args = parser.parse_args()

    # Validate input exists
    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    # Log configuration
    logger.info("=" * 60)
    logger.info("Filter Player Mentions")
    logger.info("=" * 60)
    logger.info(f"Input:  {args.input}")
    logger.info(f"Output: {args.output}")
    if args.limit:
        logger.info(f"Limit:  {args.limit:,} lines")
    logger.info("=" * 60)

    # Get input size before processing
    input_size = args.input.stat().st_size

    # Process
    stats, elapsed = process_file(
        input_path=args.input,
        output_path=args.output,
        limit=args.limit,
        skip_line_count=args.skip_line_count,
    )

    # Get output size
    output_size = args.output.stat().st_size if args.output.exists() else 0
    throughput = stats["total"] / elapsed if elapsed > 0 else 0

    # Report results
    logger.info("=" * 60)
    logger.info("Processing Complete")
    logger.info("=" * 60)
    logger.info(f"Total processed:      {stats['total']:,}")
    logger.info(f"Accepted:             {stats['accepted']:,}")
    logger.info(f"Rejected:             {stats['rejected']:,}")
    if stats["malformed"] > 0:
        logger.info(f"Malformed:            {stats['malformed']:,}")

    if stats["total"] > 0:
        acceptance_rate = (stats["accepted"] / stats["total"]) * 100
        logger.info(f"Acceptance rate:      {acceptance_rate:.2f}%")

    logger.info("")
    logger.info(f"Input size:           {format_size(input_size)}")
    logger.info(f"Output size:          {format_size(output_size)}")
    logger.info("")
    logger.info(f"Time elapsed:         {format_duration(elapsed)}")
    logger.info(f"Throughput:           {throughput:,.0f} comments/sec")


if __name__ == "__main__":
    main()
