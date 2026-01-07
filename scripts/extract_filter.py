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
from dataclasses import dataclass
from pathlib import Path

import zstandard
from tqdm import tqdm

from utils.constants import (
    TARGET_SUBREDDITS,
    INVALID_BODY_VALUES
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Statistics tracking
# ---------------------------------------------------------------------------

@dataclass
class ProcessingStats:
    """Track processing statistics for logging."""

    total_processed: int = 0
    accepted: int = 0
    rejected_subreddit: int = 0
    rejected_body: int = 0
    rejected_malformed: int = 0

    @property
    def total_rejected(self) -> int:
        return self.rejected_subreddit + self.rejected_body + self.rejected_malformed

    def log_summary(self) -> None:
        """Log final processing statistics."""
        logger.info("=" * 50)
        logger.info("Processing Complete")
        logger.info("=" * 50)
        logger.info(f"Total processed:      {self.total_processed:,}")
        logger.info(f"Accepted:             {self.accepted:,}")
        logger.info(f"Rejected (subreddit): {self.rejected_subreddit:,}")
        logger.info(f"Rejected (body):      {self.rejected_body:,}")
        logger.info(f"Rejected (malformed): {self.rejected_malformed:,}")
        if self.total_processed > 0:
            acceptance_rate = (self.accepted / self.total_processed) * 100
            logger.info(f"Acceptance rate:      {acceptance_rate:.2f}%")

# ---------------------------------------------------------------------------
# Core filtering functions
# ---------------------------------------------------------------------------

def is_target_subreddit(comment: dict) -> bool:
    """
    Check if comment is from a subreddit we're tracking.

    Args:
        comment: Raw comment dictionary from Reddit dump.

    Returns:
        True if subreddit is in our target list (case-insensitive).
    """
    subreddit = comment.get("subreddit", "")
    return subreddit.lower() in TARGET_SUBREDDITS

def has_valid_body(comment: dict) -> bool:
    """
    Check if comment has a valid, non-empty body.

    Args:
        comment: Raw comment dictionary from Reddit dump.

    Returns:
        True if body exists and is not deleted/removed/empty.
    """
    body = comment.get("body")
    if not body:
        return False
    return body not in INVALID_BODY_VALUES

def extract_fields(comment: dict) -> dict:
    """
    Extract only the fields we need from a raw comment.

    Args:
        comment: Raw comment dictionary (may have many fields).

    Returns:
        Dictionary with only the fields needed for analysis.
    """
    return {
        "id": comment.get("id"),
        "body": comment.get("body"),
        "author": comment.get("author"),
        "author_flair_text": comment.get("author_flair_text"),
        "author_flair_css_class": comment.get("author_flair_css_class"),
        "subreddit": comment.get("subreddit"),
        "created_utc": comment.get("created_utc"),
        "score": comment.get("score"),
        "controversiality": comment.get("controversiality"),
        "parent_id": comment.get("parent_id"),
        "link_id": comment.get("link_id"),
    }

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
    
def process_comment(comment: dict, stats: ProcessingStats) -> dict | None:
    """Process a single comment through the filter pipeline.

    Args:
        comment: Raw comment dictionary.
        stats: Statistics tracker (mutated in place).

    Returns:
        Extracted fields if comment passes filters, None otherwise.
    """
    stats.total_processed += 1

    if not is_target_subreddit(comment):
        stats.rejected_subreddit += 1
        return None

    if not has_valid_body(comment):
        stats.rejected_body += 1
        return None

    stats.accepted += 1
    return extract_fields(comment)

# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def process_file(input_path: Path, output_path: Path) -> ProcessingStats:
    """
    Process a ZST archive file and write filtered JSONL output.

    Args:
        input_path: Path to input .zst file.
        output_path: Path to output .jsonl file.

    Returns:
        ProcessingStats with final counts.
    """
    stats = ProcessingStats()

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
                            stats.rejected_malformed += 1
                            continue

                        result = process_comment(comment, stats)
                        if result is not None:
                            out_file.write(json.dumps(result) + "\n")

    stats.log_summary()
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