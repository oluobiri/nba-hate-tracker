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
    DEFAULT_MAX_RETRIES,
    INPUT_COST_PER_MTOK,
    MAX_TOKENS,
    OUTPUT_COST_PER_MTOK,
    REQUESTS_SUBDIR,
    RESPONSES_SUBDIR,
    STATE_FILENAME,
    calculate_cost,
    compute_run_totals,
    get_exhausted_batches,
    get_retryable_batches,
    load_state,
    mark_batch_failed,
    new_batch_entry,
    new_failed_entry,
    record_retry_attempt,
    save_state,
    submit_batch_with_retry,
)
from utils.paths import get_batches_dir
from utils.season_config import set_season_override

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


def dry_run(
    batch_files: list[Path],
    state: dict,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> None:
    """
    Validate batch files and estimate costs without making API calls.

    Args:
        batch_files: List of batch file paths.
        state: Current state dict.
        max_retries: Maximum resubmission attempts per batch.
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

    retryable = get_retryable_batches(state, max_retries)
    exhausted = get_exhausted_batches(state, max_retries)

    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    logger.info(f"Already submitted:    {len(skipped_files)} batches")
    logger.info(f"Pending submission:   {len(pending_files)} batches")
    if retryable:
        logger.info(f"Pending resubmission: {len(retryable)} failed batch(es)")
        for batch in retryable:
            logger.info(
                f"  batch {batch['batch_num']} ({batch['request_file']}): "
                f"retry {batch.get('retry_count', 0) + 1}/{max_retries}"
            )
    if exhausted:
        logger.warning(
            f"Exhausted (blocking):  {len(exhausted)} batch(es) - "
            f"submission will refuse to run"
        )
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


def fail_fast_on_exhausted(
    state: dict, state_path: Path, max_retries: int
) -> None:
    """
    Refuse to run if state holds batches that exhausted their retries.

    Marks any newly exhausted batches as terminally failed, logs each
    batch_id prominently for manual investigation, and exits.

    Args:
        state: Current state dict (will be modified).
        state_path: Path to save state file.
        max_retries: Maximum resubmission attempts per batch.
    """
    exhausted = get_exhausted_batches(state, max_retries)
    if not exhausted:
        return

    for batch in exhausted:
        if not batch.get("failed", False):
            mark_batch_failed(batch)
    save_state(state, state_path)

    logger.error("=" * 60)
    logger.error(
        f"{len(exhausted)} batch(es) failed after exhausting retries - "
        f"refusing to submit new work until resolved"
    )
    for batch in exhausted:
        logger.error(
            f"  batch {batch['batch_num']} ({batch['request_file']}): "
            f"batch_id={batch.get('batch_id')} "
            f"superseded={batch.get('superseded_batch_ids', [])}"
        )
    logger.error("Investigate these batch_ids in the Anthropic console.")
    logger.error("=" * 60)
    sys.exit(1)


def resubmit_batch(
    batch: dict,
    requests_dir: Path,
    responses_dir: Path,
    state: dict,
    state_path: Path,
    max_retries: int,
) -> None:
    """
    Resubmit a wholesale-failed batch and record the attempt in state.

    Deletes the superseded attempt's results file (if downloaded) so
    exactly one results file per batch_num survives for assembly.

    Args:
        batch: Retryable batch entry from state (will be modified).
        requests_dir: Directory containing batch request files.
        responses_dir: Directory containing downloaded results files.
        state: Current state dict (will be modified).
        state_path: Path to save state file.
        max_retries: Maximum submission attempts before terminal failure.
    """
    batch_file = requests_dir / batch["request_file"]
    attempt = batch.get("retry_count", 0) + 1
    logger.info(
        f"Resubmitting batch {batch['batch_num']} "
        f"(retry {attempt}/{max_retries}, superseding {batch.get('batch_id')})..."
    )

    stale_results = responses_dir / f"batch_{batch['batch_num']:03d}_results.jsonl"
    if stale_results.exists():
        stale_results.unlink()
        logger.info(f"  -> Deleted stale results file {stale_results.name}")

    try:
        # Submission-attempt retries are a separate dimension from the
        # wholesale-failure budget (max_retries), so always use the default
        result = submit_batch_with_retry(batch_file)
    except RuntimeError as e:
        mark_batch_failed(batch)
        save_state(state, state_path)
        logger.error(f"Resubmission failed terminally for {batch_file.name}: {e}")
        logger.error(
            f"  batch {batch['batch_num']}: "
            f"superseded={batch.get('superseded_batch_ids', [])} - "
            f"investigate in the Anthropic console"
        )
        sys.exit(1)

    record_retry_attempt(
        batch,
        submit_result=result,
        submitted_at=datetime.now(timezone.utc).isoformat(),
        estimated_cost_usd=estimate_batch_cost(count_requests(batch_file)),
    )
    state.update(compute_run_totals(state))
    save_state(state, state_path)

    logger.info(f"  -> batch_id: {result['batch_id']}, retry_count: {attempt}")


def submit_batches(
    batch_files: list[Path],
    state: dict,
    state_path: Path,
    requests_dir: Path,
    responses_dir: Path,
    max_batches: int | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_enabled: bool = True,
) -> None:
    """
    Submit batch files to the Anthropic API, resubmitting failures first.

    Refuses to run if state holds batches that exhausted their retries.
    Resubmissions of wholesale-failed batches count against max_batches
    so the one-in-flight orchestrator semantics hold.

    Args:
        batch_files: List of batch file paths.
        state: Current state dict (will be modified).
        state_path: Path to save state file.
        requests_dir: Directory containing batch request files.
        responses_dir: Directory containing downloaded results files.
        max_batches: Maximum number of batches to submit (None = all).
        max_retries: Maximum resubmission attempts per batch.
        retry_enabled: If False, skip resubmission of failed batches.
    """
    fail_fast_on_exhausted(state, state_path, max_retries)

    limit = max_batches if max_batches is not None else len(batch_files)
    submitted = 0

    retryable = get_retryable_batches(state, max_retries)
    if retryable and not retry_enabled:
        logger.warning(
            f"--no-retry: skipping {len(retryable)} retryable failed batch(es)"
        )
    elif retryable:
        for batch in retryable:
            if submitted >= limit:
                break
            try:
                resubmit_batch(
                    batch, requests_dir, responses_dir, state, state_path, max_retries
                )
            except KeyboardInterrupt:
                logger.warning("Interrupted! Saving state...")
                save_state(state, state_path)
                sys.exit(1)
            submitted += 1

    pending = [f for f in batch_files if not is_batch_submitted(state, f.name)]

    if not pending and submitted == 0:
        logger.info("No new batches to submit")
        return

    for batch_file in pending:
        if submitted >= limit:
            break
        filename = batch_file.name
        batch_num = extract_batch_num(filename)
        request_count = count_requests(batch_file)

        logger.info(f"Submitting {filename} ({request_count:,} requests)...")

        try:
            result = submit_batch_with_retry(batch_file)
        except KeyboardInterrupt:
            logger.warning("Interrupted! Saving state...")
            save_state(state, state_path)
            sys.exit(1)
        except RuntimeError as e:
            # Record a terminal entry so fail-fast trips on the next run
            state["batches"].append(
                new_failed_entry(
                    batch_num=batch_num,
                    request_file=filename,
                    attempted_at=datetime.now(timezone.utc).isoformat(),
                    retry_count=0,
                )
            )
            save_state(state, state_path)
            logger.error(f"Failed to submit {filename} terminally: {e}")
            logger.error("Marked failed in state; resolve before resubmitting.")
            sys.exit(1)

        state["batches"].append(
            new_batch_entry(
                batch_num=batch_num,
                request_file=filename,
                submit_result=result,
                submitted_at=datetime.now(timezone.utc).isoformat(),
                estimated_cost_usd=estimate_batch_cost(request_count),
            )
        )
        state.update(compute_run_totals(state))
        save_state(state, state_path)
        submitted += 1

        logger.info(
            f"  -> batch_id: {result['batch_id']}, "
            f"status: {result['processing_status']}"
        )

    logger.info("=" * 60)
    logger.info(f"Submitted {submitted} batch(es)")
    logger.info(f"State saved to: {state_path}")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point with CLI argument handling."""
    load_dotenv()

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
        help="Submit only first N pending batches (resubmissions count)",
    )
    parser.add_argument(
        "--requests-dir",
        type=Path,
        default=None,
        help="Directory containing batch files (default: <batches_dir>/requests)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        metavar="N",
        help=f"Resubmission attempts for a batch that ended with zero "
        f"successes before it is marked terminally failed "
        f"(default: {DEFAULT_MAX_RETRIES})",
    )
    parser.add_argument(
        "--no-retry",
        action="store_true",
        help="Do not resubmit failed batches (debugging escape hatch); "
        "the fail-fast gate on exhausted batches still applies",
    )
    parser.add_argument(
        "--season",
        default=None,
        metavar="YYYY-YY",
        help='Override the active season (e.g. "2024-25"); data paths and '
        "player config resolve to it for this run",
    )
    args = parser.parse_args()

    if args.season:
        set_season_override(args.season)

    # Apply defaults (after the season override so paths resolve to it)
    batches_dir = get_batches_dir()
    requests_dir = args.requests_dir or batches_dir / REQUESTS_SUBDIR
    responses_dir = batches_dir / RESPONSES_SUBDIR
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
        dry_run(batch_files, state, max_retries=args.max_retries)
    else:
        submit_batches(
            batch_files,
            state,
            state_path,
            requests_dir=requests_dir,
            responses_dir=responses_dir,
            max_batches=args.batches,
            max_retries=args.max_retries,
            retry_enabled=not args.no_retry,
        )


if __name__ == "__main__":
    main()
