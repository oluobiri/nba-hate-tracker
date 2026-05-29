"""
Process raw Reddit comments: validate, extract fields, filter to player mentions.

Combines the former clean_raw_comments.py and filter_player_mentions.py into
a single pass. Reads raw JSONL, validates bodies, extracts required fields,
filters to player mentions, and writes output JSONL.

Usage:
    # Run with defaults (recommended)
    uv run python -m scripts.process_comments

    # Explicit paths
    uv run python -m scripts.process_comments data/raw/input.jsonl data/filtered/output.jsonl

    # Preview first 10K lines (for testing)
    uv run python -m scripts.process_comments --limit 10000

Input: Raw JSONL from Arctic Shift (~60 fields per comment)
Output: Filtered JSONL with player-mentioning comments only
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from tqdm import tqdm

from pipeline.processors import (
    ProcessingStats,
    extract_fields,
    filter_player_mentions,
    has_valid_body,
)
from utils.formatting import format_duration, format_size
from utils.paths import get_filtered_dir, get_raw_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_INPUT_FILENAME = "r_nba_comments.jsonl"
DEFAULT_OUTPUT_FILENAME = "r_nba_player_mentions.jsonl"


def _count_lines(filepath: Path) -> int:
    """
    Count lines in a file for progress bar total.

    Args:
        filepath: Path to the file to count.

    Returns:
        Number of lines in the file.
    """
    logger.info("Counting lines in %s...", filepath.name)
    count = 0
    with open(filepath) as f:
        for _ in f:
            count += 1
    return count


def process_line(line: str, stats: ProcessingStats) -> dict | None:
    """
    Process a single JSON line through validate/extract/match pipeline.

    Args:
        line: Raw JSON string (one comment).
        stats: ProcessingStats object to update in place.

    Returns:
        Comment dict with mentioned_players if valid, None if rejected.
    """
    stats.total_comments += 1

    try:
        comment = json.loads(line)
    except json.JSONDecodeError:
        stats.rejected_malformed += 1
        return None

    if not has_valid_body(comment):
        stats.rejected_body += 1
        return None

    extracted = extract_fields(comment)

    result = filter_player_mentions(extracted)
    if result is None:
        stats.rejected_no_player_mention += 1
        return None

    stats.accepted_comments += 1
    return result


def process_file(
    input_path: Path,
    output_path: Path,
    limit: int | None = None,
    skip_line_count: bool = False,
) -> tuple[ProcessingStats, float]:
    """
    Stream process a raw JSONL file into filtered output.

    Args:
        input_path: Path to raw JSONL file.
        output_path: Path to write filtered JSONL.
        limit: Optional max lines to process (for testing).
        skip_line_count: Skip counting lines (faster start, no progress %).

    Returns:
        Tuple of (ProcessingStats, elapsed_seconds).
    """
    stats = ProcessingStats()

    if limit:
        total = limit
    elif skip_line_count:
        total = None
    else:
        total = _count_lines(input_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Processing %s...", input_path.name)

    start_time = time.time()

    with open(input_path) as f_in, open(output_path, "w") as f_out:
        lines = tqdm(f_in, total=total, desc="Processing", unit=" lines")

        for i, line in enumerate(lines):
            if limit and i >= limit:
                break

            line = line.strip()
            if not line:
                continue

            result = process_line(line, stats)
            if result:
                f_out.write(json.dumps(result) + "\n")

    elapsed = time.time() - start_time
    return stats, elapsed


def main() -> None:
    """Main entry point with CLI argument handling."""
    default_input = get_raw_dir() / DEFAULT_INPUT_FILENAME
    default_output = get_filtered_dir() / DEFAULT_OUTPUT_FILENAME

    parser = argparse.ArgumentParser(
        description="Process raw comments: validate, extract fields, filter to player mentions",
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=None,
        help=f"Path to raw JSONL file (default: {default_input})",
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=None,
        help=f"Path to write filtered JSONL output (default: {default_output})",
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

    if args.input is None:
        args.input = default_input
    if args.output is None:
        args.output = default_output

    if not args.input.exists():
        logger.error("Input file not found: %s", args.input)
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Process Comments")
    logger.info("=" * 60)
    logger.info("Input:  %s", args.input)
    logger.info("Output: %s", args.output)
    if args.limit:
        logger.info("Limit:  %s lines", f"{args.limit:,}")
    logger.info("=" * 60)

    input_size = args.input.stat().st_size

    stats, elapsed = process_file(
        input_path=args.input,
        output_path=args.output,
        limit=args.limit,
        skip_line_count=args.skip_line_count,
    )

    output_size = args.output.stat().st_size if args.output.exists() else 0
    size_reduction = (1 - output_size / input_size) * 100 if input_size > 0 else 0
    throughput = stats.total_comments / elapsed if elapsed > 0 else 0

    logger.info("=" * 60)
    logger.info("Processing Complete")
    logger.info("=" * 60)
    stats.log_summary(logger)
    logger.info("")
    logger.info("Input size:           %s", format_size(input_size))
    logger.info("Output size:          %s", format_size(output_size))
    logger.info("Size reduction:       %s", f"{size_reduction:.1f}%")
    logger.info("")
    logger.info("Time elapsed:         %s", format_duration(elapsed))
    logger.info("Throughput:           %s comments/sec", f"{throughput:,.0f}")


if __name__ == "__main__":
    main()
