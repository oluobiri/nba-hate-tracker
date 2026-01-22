"""
Extract and filter Reddit comments from ZST archive dumps.

Streams compressed Reddit archive files, filters for NBA-related subreddits,
validates comment bodies, and outputs clean JSONL for downstream processing.

Usage:
    uv run python scripts/extract_filter.py data/raw/RC_2024-12.zst data/filtered/RC_2024-12_filtered.jsonl
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import zstandard
from tqdm import tqdm

from pipeline.processors import CommentPipeline, has_valid_body, extract_fields
from utils.constants import TARGET_SUBREDDITS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Statistics logging
# ---------------------------------------------------------------------------


def log_stats_summary(stats: dict[str, int]) -> None:
    """
    Log final processing statistics.

    Args:
        stats: Dictionary with 'total', 'accepted', and 'rejected_*' keys.
    """
    logger.info("=" * 50)
    logger.info("Processing Complete")
    logger.info("=" * 50)
    logger.info(f"Total processed:      {stats['total']:,}")
    logger.info(f"Accepted:             {stats['accepted']:,}")

    # Log rejection counts
    for key, value in stats.items():
        if key.startswith("rejected_"):
            step_name = key.replace("rejected_", "")
            logger.info(f"Rejected ({step_name}): {value:,}")

    if stats["total"] > 0:
        acceptance_rate = (stats["accepted"] / stats["total"]) * 100
        logger.info(f"Acceptance rate:      {acceptance_rate:.2f}%")


# ---------------------------------------------------------------------------
# Core filtering functions
# ---------------------------------------------------------------------------


def is_target_subreddit(comment: dict) -> dict | None:
    """
    Check if comment is from a subreddit we're tracking.

    Args:
        comment: Raw comment dictionary from Reddit dump.

    Returns:
        Original comment if subreddit is in our target list, None otherwise.
    """
    subreddit = comment.get("subreddit", "")
    if subreddit.lower() in TARGET_SUBREDDITS:
        return comment
    return None


# ---------------------------------------------------------------------------
# Streaming processing
# ---------------------------------------------------------------------------


def stream_zst_lines(filepath: Path, chunk_size: int = 1024 * 1024 * 16):
    """
    Stream lines from a zstandard-compressed file.

    Uses chunked decompression to handle files larger than memory.

    Args:
        filepath: Path to .zst file.
        chunk_size: Bytes to read per chunk (default 16MB).

    Yields:
        Individual lines (strings) from the decompressed content.
    """
    decompressor = zstandard.ZstdDecompressor(max_window_size=2**31)

    with open(filepath, "rb") as fh:
        reader = decompressor.stream_reader(fh)
        buffer = ""

        while True:
            chunk = reader.read(chunk_size)
            if not chunk:
                break

            buffer += chunk.decode("utf-8", errors="replace")
            lines = buffer.split("\n")

            # Last element might be incomplete — keep in buffer
            buffer = lines[-1]

            for line in lines[:-1]:
                if line.strip():
                    yield line


def parse_json_line(line: str) -> dict | None:
    """
    Safely parse a JSON line.

    Args:
        line: Raw JSON string.

    Returns:
        Parsed dictionary, or None if parsing fails.
    """
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def process_file(input_path: Path, output_path: Path) -> dict[str, int]:
    """
    Process a ZST archive file and write filtered JSONL output.

    Args:
        input_path: Path to input .zst file.
        output_path: Path to output .jsonl file.

    Returns:
        Stats dict with processing counts.
    """
    # Build pipeline
    pipeline = CommentPipeline()
    pipeline.add_step(is_target_subreddit)
    pipeline.add_step(has_valid_body)
    pipeline.add_step(extract_fields)

    malformed_count = 0

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Processing: {input_path}")
    logger.info(f"Output: {output_path}")

    # Get file size for progress bar
    file_size = input_path.stat().st_size

    with open(output_path, "w", encoding="utf-8") as out_file:
        with tqdm(
            total=file_size,
            unit="B",
            unit_scale=True,
            desc="Processing",
        ) as pbar:
            # Track bytes for progress updates
            last_position = 0

            with open(input_path, "rb") as in_file:
                decompressor = zstandard.ZstdDecompressor(max_window_size=2**31)
                reader = decompressor.stream_reader(in_file)
                buffer = ""
                chunk_size = 1024 * 1024 * 16  # 16MB chunks

                while True:
                    chunk = reader.read(chunk_size)
                    if not chunk:
                        break

                    # Update progress bar based on compressed bytes read
                    current_position = in_file.tell()
                    pbar.update(current_position - last_position)
                    last_position = current_position

                    buffer += chunk.decode("utf-8", errors="replace")
                    lines = buffer.split("\n")
                    buffer = lines[-1]

                    for line in lines[:-1]:
                        if not line.strip():
                            continue

                        comment = parse_json_line(line)
                        if comment is None:
                            malformed_count += 1
                            continue

                        result = pipeline.process(comment)
                        if result is not None:
                            out_file.write(json.dumps(result) + "\n")

    # Combine stats
    stats = pipeline.stats
    stats["rejected_malformed"] = malformed_count

    log_stats_summary(stats)
    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Extract and filter Reddit comments from ZST archives."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to input .zst file",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="Path to output .jsonl file",
    )
    args = parser.parse_args()

    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    if not args.input.suffix == ".zst":
        logger.warning(f"Input file does not have .zst extension: {args.input}")

    process_file(args.input, args.output)


if __name__ == "__main__":
    main()
