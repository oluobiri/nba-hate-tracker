"""
Clean raw Reddit comments downloaded from Arctic Shift.

Streams through raw JSONL, validates comment bodies, extracts only the fields
we need, and outputs a cleaned JSONL file ready for downstream processing.

Usage:
    # Run with defaults (recommended)
    uv run python scripts/clean_raw_comments.py

    # Explicit paths
    uv run python scripts/clean_raw_comments.py data/raw/r_nba_comments.jsonl data/filtered/r_nba_cleaned.jsonl

    # Preview first 10K lines (for testing)
    uv run python scripts/clean_raw_comments.py --limit 10000

Input: Raw JSONL from Arctic Shift (~60 fields per comment)
Output: Cleaned JSONL with 11 fields, invalid bodies removed
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from tqdm import tqdm

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.extract_filter import (
    ProcessingStats,
    has_valid_body,
    extract_fields,
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
# Default paths
# -----------------------------------------------------------------------------

DEFAULT_INPUT = Path("data/raw/r_nba_comments.jsonl")
DEFAULT_OUTPUT = Path("data/filtered/r_nba_cleaned.jsonl")


# -----------------------------------------------------------------------------
# Core processing
# -----------------------------------------------------------------------------


def count_lines(filepath: Path) -> int:
    """
    Count lines in a file for progress bar total.
    
    For very large files, this adds startup time but makes the progress
    bar much more useful. On a 13GB file, expect ~30-60 seconds.
    """
    logger.info(f"Counting lines in {filepath.name}...")
    count = 0
    with open(filepath, "r") as f:
        for _ in f:
            count += 1
    return count


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string (KB, MB, GB)."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours}h {minutes}m {secs}s"


def process_line(line: str, stats: ProcessingStats) -> dict | None:
    """
    Process a single JSON line from raw input.
    
    Args:
        line: Raw JSON string (one comment)
        stats: ProcessingStats object to update
        
    Returns:
        Extracted comment dict if valid, None if rejected
    """
    stats.total_processed += 1
    
    # Parse JSON
    try:
        comment = json.loads(line)
    except json.JSONDecodeError:
        stats.rejected_malformed += 1
        return None
    
    # Validate body
    if not has_valid_body(comment):
        stats.rejected_body += 1
        return None
    
    # Extract fields and accept
    stats.accepted += 1
    return extract_fields(comment)


def process_file(
    input_path: Path,
    output_path: Path,
    limit: int | None = None,
    skip_line_count: bool = False,
) -> tuple[ProcessingStats, float]:
    """
    Stream process a raw JSONL file into cleaned output.
    
    Args:
        input_path: Path to raw JSONL file
        output_path: Path to write cleaned JSONL
        limit: Optional max lines to process (for testing)
        skip_line_count: Skip counting lines (faster start, no progress %)
        
    Returns:
        Tuple of (ProcessingStats, elapsed_seconds)
    """
    stats = ProcessingStats()
    
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
    
    with open(input_path, "r") as f_in, open(output_path, "w") as f_out:
        
        # tqdm wraps the file iterator for progress tracking
        lines = tqdm(f_in, total=total, desc="Processing", unit=" lines")
        
        for i, line in enumerate(lines):
            # Check limit
            if limit and i >= limit:
                break
            
            # Skip empty lines
            line = line.strip()
            if not line:
                continue
            
            # Process and write if valid
            result = process_line(line, stats)
            if result:
                f_out.write(json.dumps(result) + "\n")
    
    elapsed = time.time() - start_time
    
    return stats, elapsed


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point with CLI argument handling."""
    parser = argparse.ArgumentParser(
        description="Clean raw Reddit comments: validate bodies, extract fields"
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=DEFAULT_INPUT,
        help=f"Path to raw JSONL file (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=DEFAULT_OUTPUT,
        help=f"Path to write cleaned JSONL output (default: {DEFAULT_OUTPUT})",
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
    logger.info("Clean Raw Comments")
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
    size_reduction = (1 - output_size / input_size) * 100 if input_size > 0 else 0
    throughput = stats.total_processed / elapsed if elapsed > 0 else 0
    
    # Report results
    logger.info("=" * 60)
    logger.info("Processing Complete")
    logger.info("=" * 60)
    logger.info(f"Total processed:      {stats.total_processed:,}")
    logger.info(f"Accepted:             {stats.accepted:,}")
    logger.info(f"Rejected (body):      {stats.rejected_body:,}")
    logger.info(f"Rejected (malformed): {stats.rejected_malformed:,}")
    
    if stats.total_processed > 0:
        acceptance_rate = (stats.accepted / stats.total_processed) * 100
        logger.info(f"Acceptance rate:      {acceptance_rate:.2f}%")
    
    logger.info("")
    logger.info(f"Input size:           {format_size(input_size)}")
    logger.info(f"Output size:          {format_size(output_size)}")
    logger.info(f"Size reduction:       {size_reduction:.1f}%")
    logger.info("")
    logger.info(f"Time elapsed:         {format_duration(elapsed)}")
    logger.info(f"Throughput:           {throughput:,.0f} comments/sec")


if __name__ == "__main__":
    main()
