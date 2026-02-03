"""
Prepare batch request files for Anthropic Batch API.

Transforms filtered comments into JSONL files formatted for the
Anthropic Batch API. Splits output at REQUESTS_PER_BATCH (100K) boundary.

Usage:
    # Run with defaults (recommended)
    uv run python -m scripts.prepare_batches

    # With explicit input
    uv run python -m scripts.prepare_batches --input data/filtered/r_nba_player_mentions.jsonl

    # Preview first 1K comments (for testing)
    uv run python -m scripts.prepare_batches --limit 1000

Input: Filtered JSONL from filter_player_mentions.py
Output: data/batches/requests/batch_NNN.jsonl files
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from tqdm import tqdm

from pipeline.batch import format_batch_request, REQUESTS_PER_BATCH
from utils.formatting import format_duration
from utils.paths import get_batches_dir, get_filtered_dir

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
# Default filenames
# -----------------------------------------------------------------------------

DEFAULT_INPUT_FILENAME = "r_nba_player_mentions.jsonl"
REQUESTS_SUBDIR = "requests"


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


def write_batch(output_dir: Path, batch_num: int, requests: list[dict]) -> None:
    """
    Write a batch of requests to a JSONL file.

    Args:
        output_dir: Directory to write the batch file.
        batch_num: Batch number for filename.
        requests: List of batch request dicts to write.
    """
    batch_path = output_dir / f"batch_{batch_num:03d}.jsonl"
    with open(batch_path, "w") as f:
        for request in requests:
            f.write(json.dumps(request) + "\n")


def process_file(
    input_path: Path,
    output_dir: Path,
    limit: int | None = None,
    skip_line_count: bool = False,
) -> tuple[dict[str, int], float]:
    """
    Transform filtered comments into batch request files.

    Args:
        input_path: Path to input JSONL file.
        output_dir: Directory to write batch request files.
        limit: Optional max comments to process (for testing).
        skip_line_count: Skip counting lines (faster start, no progress %).

    Returns:
        Tuple of (stats dict, elapsed_seconds).
    """
    stats = {
        "total": 0,
        "batches": 0,
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
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Processing {input_path.name}...")

    start_time = time.time()

    batch_num = 0
    current_batch: list[dict] = []

    with open(input_path) as f_in:
        lines = tqdm(f_in, total=total, desc="Preparing", unit=" comments")

        for line in lines:
            if limit and stats["total"] >= limit:
                break

            line = line.strip()
            if not line:
                continue

            # Parse JSON
            try:
                comment = json.loads(line)
            except json.JSONDecodeError:
                stats["malformed"] += 1
                continue

            request = format_batch_request(comment)
            current_batch.append(request)
            stats["total"] += 1

            # Write batch when full
            if len(current_batch) >= REQUESTS_PER_BATCH:
                batch_num += 1
                write_batch(output_dir, batch_num, current_batch)
                stats["batches"] += 1
                current_batch = []

    # Write remaining requests
    if current_batch:
        batch_num += 1
        write_batch(output_dir, batch_num, current_batch)
        stats["batches"] += 1

    elapsed = time.time() - start_time
    return stats, elapsed


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point with CLI argument handling."""
    # Resolve default paths at runtime
    filtered_dir = get_filtered_dir()
    batches_dir = get_batches_dir()
    default_input = filtered_dir / DEFAULT_INPUT_FILENAME
    default_output = batches_dir / REQUESTS_SUBDIR

    parser = argparse.ArgumentParser(
        description="Prepare batch request files for Anthropic Batch API"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help=f"Path to input JSONL file (default: {default_input})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Directory to write batch files (default: {default_output})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only first N comments (for testing)",
    )
    parser.add_argument(
        "--skip-line-count",
        action="store_true",
        help="Skip counting lines (faster start, but no progress percentage)",
    )
    args = parser.parse_args()

    # Apply defaults after parsing
    if args.input is None:
        args.input = default_input
    if args.output is None:
        args.output = default_output

    # Validate input exists
    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    # Log configuration
    logger.info("=" * 60)
    logger.info("Prepare Batch Requests")
    logger.info("=" * 60)
    logger.info(f"Input:  {args.input}")
    logger.info(f"Output: {args.output}/")
    logger.info(f"Max requests per batch: {REQUESTS_PER_BATCH:,}")
    if args.limit:
        logger.info(f"Limit:  {args.limit:,} comments")
    logger.info("=" * 60)

    # Process
    stats, elapsed = process_file(
        input_path=args.input,
        output_dir=args.output,
        limit=args.limit,
        skip_line_count=args.skip_line_count,
    )

    throughput = stats["total"] / elapsed if elapsed > 0 else 0

    # Report results
    logger.info("=" * 60)
    logger.info("Processing Complete")
    logger.info("=" * 60)
    logger.info(f"Total processed:      {stats['total']:,}")
    logger.info(f"Batches created:      {stats['batches']}")
    if stats["malformed"] > 0:
        logger.info(f"Malformed (skipped):  {stats['malformed']:,}")
    logger.info("")
    logger.info(f"Time elapsed:         {format_duration(elapsed)}")
    logger.info(f"Throughput:           {throughput:,.0f} comments/sec")


if __name__ == "__main__":
    main()
