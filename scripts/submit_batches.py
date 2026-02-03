"""
Submit batch files to the Anthropic Batch API.

Submits prepared batch request files to the Anthropic Batch API with
state tracking for resumability. Supports dry-run mode for cost estimation.

Usage:
    # Dry run - validate and estimate costs (no API calls)
    uv run python -m scripts.submit_batches --dry-run

    # Submit first batch only (for testing)
    uv run python -m scripts.submit_batches --batches 1

    # Submit all pending batches
    uv run python -m scripts.submit_batches

    # Resume after interruption (automatically skips submitted batches)
    uv run python -m scripts.submit_batches

Input: data/batches/requests/batch_NNN.jsonl files
Output: data/batches/state.json tracking file
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv

from pipeline.batch import (
    INPUT_COST_PER_MTOK,
    MAX_TOKENS,
    OUTPUT_COST_PER_MTOK,
    STATE_FILENAME,
    calculate_cost,
    load_state,
    save_state,
    submit_batch,
)
from utils.paths import get_batches_dir

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
# Constants
# -----------------------------------------------------------------------------

REQUESTS_SUBDIR = "requests"
AVG_INPUT_TOKENS = 60  # From notebook cost analysis


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------


def discover_batch_files(requests_dir: Path) -> list[Path]:
    """
    Discover batch files in the requests directory.

    Args:
        requests_dir: Path to directory containing batch_NNN.jsonl files.

    Returns:
        Sorted list of batch file paths.
    """
    if not requests_dir.exists():
        return []

    files = sorted(requests_dir.glob("batch_*.jsonl"))
    return files


def is_batch_submitted(state: dict, filename: str) -> bool:
    """
    Check if a batch file has already been submitted.

    Args:
        state: Current state dict.
        filename: Batch filename to check.

    Returns:
        True if already submitted, False otherwise.
    """
    return any(b["request_file"] == filename for b in state.get("batches", []))


def count_requests(batch_file: Path) -> int:
    """
    Count the number of requests in a batch file.

    Args:
        batch_file: Path to JSONL batch file.

    Returns:
        Number of non-empty lines (requests) in the file.
    """
    count = 0
    with open(batch_file) as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def validate_batch_file(batch_file: Path) -> tuple[bool, str]:
    """
    Validate a batch file has valid JSONL with required fields.

    Args:
        batch_file: Path to JSONL batch file.

    Returns:
        Tuple of (is_valid, error_message).
    """
    try:
        with open(batch_file) as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    request = json.loads(line)
                except json.JSONDecodeError as e:
                    return False, f"Line {i}: Invalid JSON - {e}"

                if "custom_id" not in request:
                    return False, f"Line {i}: Missing 'custom_id' field"
                if "params" not in request:
                    return False, f"Line {i}: Missing 'params' field"

        return True, ""
    except OSError as e:
        return False, f"Cannot read file: {e}"


def estimate_batch_cost(request_count: int) -> float:
    """
    Estimate cost for a batch based on request count.

    Uses average input tokens from notebook analysis and MAX_TOKENS for output.

    Args:
        request_count: Number of requests in the batch.

    Returns:
        Estimated cost in USD.
    """
    total_input = request_count * AVG_INPUT_TOKENS
    total_output = request_count * MAX_TOKENS
    return calculate_cost(total_input, total_output)


def extract_batch_num(filename: str) -> int:
    """
    Extract batch number from filename like 'batch_001.jsonl'.

    Args:
        filename: Batch filename.

    Returns:
        Batch number as integer.
    """
    # batch_001.jsonl -> 001 -> 1
    stem = filename.replace(".jsonl", "")
    num_str = stem.split("_")[1]
    return int(num_str)


# -----------------------------------------------------------------------------
# Dry run
# -----------------------------------------------------------------------------


def dry_run(batch_files: list[Path], state: dict) -> None:
    """
    Validate batch files and estimate costs without making API calls.

    Args:
        batch_files: List of batch file paths.
        state: Current state dict.
    """
    logger.info("DRY RUN MODE - No API calls will be made")
    logger.info("=" * 60)

    total_requests = 0
    total_cost = 0.0
    pending_files = []
    skipped_files = []

    for batch_file in batch_files:
        filename = batch_file.name

        if is_batch_submitted(state, filename):
            skipped_files.append(filename)
            continue

        # Validate
        is_valid, error = validate_batch_file(batch_file)
        if not is_valid:
            logger.error(f"Invalid batch file {filename}: {error}")
            sys.exit(1)

        # Count and estimate
        request_count = count_requests(batch_file)
        estimated_cost = estimate_batch_cost(request_count)

        logger.info(
            f"  {filename}: {request_count:,} requests, "
            f"~${estimated_cost:.2f}"
        )

        total_requests += request_count
        total_cost += estimated_cost
        pending_files.append(filename)

    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    logger.info(f"Already submitted:    {len(skipped_files)} batches")
    logger.info(f"Pending submission:   {len(pending_files)} batches")
    logger.info(f"Total requests:       {total_requests:,}")
    logger.info(f"Estimated cost:       ${total_cost:.2f}")
    logger.info("")
    logger.info("Cost calculation assumptions:")
    logger.info(f"  - Input tokens/request:  {AVG_INPUT_TOKENS}")
    logger.info(f"  - Output tokens/request: {MAX_TOKENS} (max)")
    logger.info(f"  - Input cost:  ${INPUT_COST_PER_MTOK}/M tokens")
    logger.info(f"  - Output cost: ${OUTPUT_COST_PER_MTOK}/M tokens")


# -----------------------------------------------------------------------------
# Submission
# -----------------------------------------------------------------------------


def submit_batches(
    batch_files: list[Path],
    state: dict,
    state_path: Path,
    max_batches: int | None = None,
) -> None:
    """
    Submit batch files to the Anthropic API.

    Args:
        batch_files: List of batch file paths.
        state: Current state dict (will be modified).
        state_path: Path to save state file.
        max_batches: Maximum number of batches to submit (None = all).
    """
    pending = [
        f for f in batch_files if not is_batch_submitted(state, f.name)
    ]

    if not pending:
        logger.info("No new batches to submit")
        return

    if max_batches is not None:
        pending = pending[:max_batches]

    logger.info(f"Submitting {len(pending)} batch(es)...")
    logger.info("=" * 60)

    for batch_file in pending:
        filename = batch_file.name
        batch_num = extract_batch_num(filename)
        request_count = count_requests(batch_file)

        logger.info(f"Submitting {filename} ({request_count:,} requests)...")

        try:
            result = submit_batch(batch_file)

            # Add to state
            batch_entry = {
                "batch_num": batch_num,
                "batch_id": result["batch_id"],
                "request_file": filename,
                "status": result["processing_status"],
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "ended_at": result["ended_at"],
                "results_url": result["results_url"],
                "request_counts": result["request_counts"],
                "results_downloaded": False,
            }
            state["batches"].append(batch_entry)

            # Save state immediately
            save_state(state, state_path)

            logger.info(
                f"  -> batch_id: {result['batch_id']}, "
                f"status: {result['processing_status']}"
            )

        except KeyboardInterrupt:
            logger.warning("Interrupted! Saving state...")
            save_state(state, state_path)
            sys.exit(1)

        except Exception as e:
            logger.error(f"Failed to submit {filename}: {e}")
            save_state(state, state_path)
            raise

    logger.info("=" * 60)
    logger.info(f"Submitted {len(pending)} batch(es)")
    logger.info(f"State saved to: {state_path}")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point with CLI argument handling."""
    load_dotenv()
    batches_dir = get_batches_dir()
    default_requests_dir = batches_dir / REQUESTS_SUBDIR

    parser = argparse.ArgumentParser(
        description="Submit batch files to Anthropic Batch API"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate files and estimate cost without making API calls",
    )
    parser.add_argument(
        "--batches",
        type=int,
        default=None,
        metavar="N",
        help="Submit only first N pending batches",
    )
    parser.add_argument(
        "--requests-dir",
        type=Path,
        default=None,
        help=f"Directory containing batch files (default: {default_requests_dir})",
    )
    args = parser.parse_args()

    # Apply defaults
    requests_dir = args.requests_dir or default_requests_dir
    state_path = batches_dir / STATE_FILENAME

    # Discover batch files
    batch_files = discover_batch_files(requests_dir)

    if not batch_files:
        logger.error(f"No batch files found in {requests_dir}")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Submit Batches to Anthropic API")
    logger.info("=" * 60)
    logger.info(f"Requests dir: {requests_dir}")
    logger.info(f"State file:   {state_path}")
    logger.info(f"Found:        {len(batch_files)} batch file(s)")
    logger.info("=" * 60)

    # Load state
    state = load_state(state_path)
    submitted_count = len(state.get("batches", []))
    if submitted_count > 0:
        logger.info(f"Resuming: {submitted_count} batch(es) already submitted")

    if args.dry_run:
        dry_run(batch_files, state)
    else:
        submit_batches(batch_files, state, state_path, max_batches=args.batches)


if __name__ == "__main__":
    main()
