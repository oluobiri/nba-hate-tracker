"""
Collect batch results from the Anthropic Batch API.

Polls for batch completion, downloads results, and produces the final
sentiment.parquet file with parsed classifications joined to comment metadata.

Usage:
    # Check status and download completed batches (no waiting)
    uv run python -m scripts.collect_results --no-wait

    # Poll until all batches complete (default: check every 60s, max 24h)
    uv run python -m scripts.collect_results

    # Custom poll settings
    uv run python -m scripts.collect_results --poll-interval 120 --max-wait 3600

Input: data/batches/state.json, data/batches/requests/batch_NNN.jsonl
Output:
    - data/batches/responses/batch_NNN_results.jsonl (per batch)
    - data/processed/sentiment.parquet (final joined output)
    - data/batches/failed_requests.jsonl (if any failures)
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from pipeline.batch import (
    REQUESTS_SUBDIR,
    RESPONSES_SUBDIR,
    STATE_FILENAME,
    compute_run_totals,
    download_results,
    get_batch_status,
    get_downloadable_batches,
    get_missing_results,
    get_pending_batches,
    get_unsubmitted_request_files,
    is_wholesale_failure,
    load_state,
    save_state,
    summarize_actual_usage,
)
from pipeline.results import build_sentiment_dataframe
from utils.paths import get_batches_dir, get_filtered_dir, get_processed_dir
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

FILTERED_FILENAME = "r_nba_player_mentions.jsonl"
OUTPUT_FILENAME = "sentiment.parquet"
FAILED_FILENAME = "failed_requests.jsonl"

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------


def poll_batch_statuses(state: dict) -> int:
    """
    Update status for all pending batches.

    Args:
        state: Current state dict (modified in place).

    Returns:
        Number of batches that transitioned to "ended" status.
    """
    pending = get_pending_batches(state)
    newly_completed = 0

    for batch in pending:
        batch_id = batch["batch_id"]
        try:
            status = get_batch_status(batch_id)
            old_status = batch.get("status")
            batch["status"] = status["processing_status"]
            batch["request_counts"] = status["request_counts"]
            batch["ended_at"] = status["ended_at"]
            batch["results_url"] = status["results_url"]

            if old_status != "ended" and status["processing_status"] == "ended":
                newly_completed += 1
                if is_wholesale_failure(batch):
                    logger.warning(
                        f"Batch {batch['batch_num']} ended with ZERO successes "
                        f"(attempt {batch.get('retry_count', 0) + 1}) - "
                        f"eligible for retry via submit_batches"
                    )
                else:
                    logger.info(
                        f"Batch {batch['batch_num']} completed: "
                        f"{status['request_counts']['succeeded']} succeeded, "
                        f"{status['request_counts']['errored']} errored"
                    )
            else:
                logger.debug(
                    f"Batch {batch['batch_num']}: {status['processing_status']}"
                )

        except RuntimeError as e:
            logger.error(f"Failed to get status for batch {batch_id}: {e}")

    return newly_completed


def download_batch_results(batch: dict, responses_dir: Path) -> Path:
    """
    Download and save results for a single batch.

    Args:
        batch: Batch entry dict from state.
        responses_dir: Directory to save results.

    Returns:
        Path to the saved results file.
    """
    batch_id = batch["batch_id"]
    batch_num = batch["batch_num"]
    output_file = responses_dir / f"batch_{batch_num:03d}_results.jsonl"

    logger.info(f"Downloading results for batch {batch_num}...")

    results = download_results(batch_id)

    responses_dir.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        for result in results:
            f.write(json.dumps(result) + "\n")

    succeeded = sum(1 for r in results if r["result_type"] == "succeeded")
    errored = sum(1 for r in results if r["result_type"] != "succeeded")
    logger.info(
        f"  -> Saved {len(results)} results ({succeeded} succeeded, {errored} failed)"
    )

    # Reconcile actual token usage into the batch entry
    batch.update(summarize_actual_usage(results))
    logger.info(
        f"  -> Actual cost: ${batch['actual_cost_usd']:.2f} "
        f"(estimated: ${batch.get('estimated_cost_usd', 0.0):.2f})"
    )

    return output_file


def poll_until_complete(
    state: dict,
    state_path: Path,
    responses_dir: Path,
    poll_interval: int,
    max_wait: int,
) -> bool:
    """
    Poll until all batches complete or timeout.

    Downloads results as batches complete.

    Args:
        state: Current state dict (modified in place).
        state_path: Path to save state file.
        responses_dir: Directory to save results.
        poll_interval: Seconds between status checks.
        max_wait: Maximum wait time in seconds.

    Returns:
        True if all batches in state completed (the run may still have
        unsubmitted request files), False if timeout.
    """
    start_time = time.time()

    while True:
        # Check for newly completed batches
        poll_batch_statuses(state)
        save_state(state, state_path)

        # Download any completed batches
        downloadable = get_downloadable_batches(state)
        for batch in downloadable:
            try:
                download_batch_results(batch, responses_dir)
                batch["results_downloaded"] = True
                state.update(compute_run_totals(state))
                save_state(state, state_path)
            except RuntimeError as e:
                logger.error(f"Failed to download batch {batch['batch_num']}: {e}")

        # Check if all done (state-scoped: submitted batches only)
        pending = get_pending_batches(state)
        if not pending:
            logger.info("All submitted batches completed")
            return True

        # Check timeout
        elapsed = time.time() - start_time
        if elapsed >= max_wait:
            logger.warning(
                f"Timeout after {elapsed:.0f}s with {len(pending)} batches pending"
            )
            return False

        # Wait before next poll
        remaining = max_wait - elapsed
        wait_time = min(poll_interval, remaining)
        logger.info(
            f"Waiting {wait_time:.0f}s... "
            f"({len(pending)} batches pending, {remaining:.0f}s remaining)"
        )
        time.sleep(wait_time)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point with CLI argument handling."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Collect batch results from Anthropic Batch API"
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=60,
        metavar="N",
        help="Seconds between status checks (default: 60)",
    )
    parser.add_argument(
        "--max-wait",
        type=int,
        default=86400,
        metavar="N",
        help="Maximum wait time in seconds (default: 86400 = 24h)",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Check once, download completed batches, and exit",
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

    # Setup paths
    batches_dir = get_batches_dir()
    state_path = batches_dir / STATE_FILENAME
    requests_dir = batches_dir / REQUESTS_SUBDIR
    responses_dir = batches_dir / RESPONSES_SUBDIR
    filtered_path = get_filtered_dir() / FILTERED_FILENAME
    processed_dir = get_processed_dir()
    output_path = processed_dir / OUTPUT_FILENAME
    failed_path = batches_dir / FAILED_FILENAME

    logger.info("=" * 60)
    logger.info("Collect Batch Results")
    logger.info("=" * 60)
    logger.info(f"State file:    {state_path}")
    logger.info(f"Responses dir: {responses_dir}")
    logger.info(f"Output file:   {output_path}")
    logger.info("=" * 60)

    # Load state
    state = load_state(state_path)
    batch_count = len(state.get("batches", []))

    if batch_count == 0:
        logger.error("No batches found in state. Run submit_batches.py first.")
        sys.exit(1)

    if not filtered_path.exists():
        logger.error(f"Filtered comments file not found: {filtered_path}")
        sys.exit(1)

    logger.info(f"Found {batch_count} batch(es) in state")

    # Collect never submits, so the set of request files with state
    # entries is fixed for this run - compute the reconciliation once.
    unsubmitted = get_unsubmitted_request_files(state, requests_dir)

    # Handle --no-wait mode
    if args.no_wait:
        logger.info("Running in --no-wait mode (single check)")

        # Update statuses
        poll_batch_statuses(state)
        save_state(state, state_path)

        # Download completed batches
        downloadable = get_downloadable_batches(state)
        for batch in downloadable:
            try:
                download_batch_results(batch, responses_dir)
                batch["results_downloaded"] = True
                state.update(compute_run_totals(state))
                save_state(state, state_path)
            except RuntimeError as e:
                logger.error(f"Failed to download batch {batch['batch_num']}: {e}")

        pending = get_pending_batches(state)
        if pending:
            logger.info(f"{len(pending)} batch(es) still pending")
        elif not unsubmitted:
            # With unsubmitted request files, "complete" would be a lie
            # (#71's state-vs-reality trap); the guard below logs the
            # cycle's one summary line instead.
            logger.info("All batches completed!")

    else:
        # Poll until complete or timeout
        logger.info(f"Polling every {args.poll_interval}s (max {args.max_wait}s)...")
        completed = poll_until_complete(
            state, state_path, responses_dir, args.poll_interval, args.max_wait
        )
        if not completed:
            logger.warning("Exiting with pending batches due to timeout")

    # Mid-run guard (#71): state only knows about submitted batches; the
    # requests directory is the ground truth of the full population.
    if unsubmitted:
        total = len(list(requests_dir.glob("batch_*.jsonl")))
        logger.info(
            f"{total - len(unsubmitted)}/{total} request files submitted - "
            f"downloading available results, skipping parquet build"
        )
        sys.exit(0)

    # Check if we can build the final output
    pending = get_pending_batches(state)
    not_downloaded = get_missing_results(state)

    if pending or not_downloaded:
        logger.info(
            f"Cannot build final output: {len(pending)} pending, "
            f"{len(not_downloaded)} not downloaded"
        )
        sys.exit(0)

    # Build final sentiment.parquet
    failed_batches = [b for b in state.get("batches", []) if b.get("failed", False)]
    if failed_batches:
        logger.warning("=" * 60)
        logger.warning(
            f"{len(failed_batches)} batch(es) FAILED terminally - their requests "
            f"are missing from the output. Building anyway; re-run after manual "
            f"recovery to rebuild."
        )
        for batch in failed_batches:
            logger.warning(
                f"  batch {batch['batch_num']}: batch_id={batch.get('batch_id')}"
            )
        logger.warning("=" * 60)

    logger.info("=" * 60)
    logger.info("Building sentiment.parquet...")
    logger.info("=" * 60)

    try:
        sentiment_df, failed_requests = build_sentiment_dataframe(
            responses_dir, filtered_path
        )

        # Save parquet
        processed_dir.mkdir(parents=True, exist_ok=True)
        sentiment_df.write_parquet(output_path)
        logger.info(f"Wrote {len(sentiment_df)} rows to {output_path}")

        # Save failed requests
        if failed_requests:
            with open(failed_path, "w") as f:
                for req in failed_requests:
                    f.write(json.dumps(req) + "\n")
            logger.warning(
                f"Wrote {len(failed_requests)} failed requests to {failed_path}"
            )

        # Update and save final state
        state.update(compute_run_totals(state))
        save_state(state, state_path)
        logger.info("=" * 60)
        logger.info("Summary")
        logger.info("=" * 60)
        logger.info(f"Total input tokens:  {state['total_input_tokens']:,}")
        logger.info(f"Total output tokens: {state['total_output_tokens']:,}")
        logger.info(f"Estimated cost:      ${state['estimated_cost_usd']:.2f}")
        logger.info(f"Actual cost:         ${state['actual_cost_usd']:.2f}")

    except FileNotFoundError as e:
        logger.error(f"Missing file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to build output: {e}")
        raise


if __name__ == "__main__":
    main()
