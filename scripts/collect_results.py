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

import polars as pl
from dotenv import load_dotenv

from pipeline.batch import (
    STATE_FILENAME,
    calculate_cost,
    download_results,
    get_batch_status,
    load_state,
    parse_response,
    save_state,
)
from utils.paths import get_batches_dir, get_filtered_dir, get_processed_dir

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

RESPONSES_SUBDIR = "responses"
FILTERED_FILENAME = "r_nba_player_mentions.jsonl"
OUTPUT_FILENAME = "sentiment.parquet"
FAILED_FILENAME = "failed_requests.jsonl"

# Output columns for sentiment.parquet
OUTPUT_COLUMNS = [
    "comment_id",
    "body",
    "author",
    "author_flair_text",
    "author_flair_css_class",
    "created_utc",
    "score",
    "mentioned_players",
    "sentiment",
    "confidence",
    "sentiment_player",
    "input_tokens",
    "output_tokens",
]


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------


def get_pending_batches(state: dict) -> list[dict]:
    """
    Get batches that haven't finished processing yet.

    Args:
        state: Current state dict.

    Returns:
        List of batch entries with status != "ended".
    """
    return [b for b in state.get("batches", []) if b.get("status") != "ended"]


def get_downloadable_batches(state: dict) -> list[dict]:
    """
    Get batches that are complete but haven't had results downloaded.

    Args:
        state: Current state dict.

    Returns:
        List of batch entries with status == "ended" and results_downloaded == False.
    """
    return [
        b
        for b in state.get("batches", [])
        if b.get("status") == "ended" and not b.get("results_downloaded", False)
    ]


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
        True if all batches completed, False if timeout.
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
                save_state(state, state_path)
            except RuntimeError as e:
                logger.error(f"Failed to download batch {batch['batch_num']}: {e}")

        # Check if all done
        pending = get_pending_batches(state)
        if not pending:
            logger.info("All batches completed!")
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


def build_sentiment_dataframe(
    responses_dir: Path, filtered_path: Path, state: dict
) -> tuple[pl.DataFrame, list[dict]]:
    """
    Build sentiment DataFrame by joining results with comment metadata.

    Args:
        responses_dir: Directory containing batch_NNN_results.jsonl files.
        filtered_path: Path to filtered comments JSONL file.
        state: State dict to update with token totals.

    Returns:
        Tuple of (sentiment DataFrame, list of failed requests).
    """
    # Load all results
    results_files = sorted(responses_dir.glob("batch_*_results.jsonl"))
    if not results_files:
        raise FileNotFoundError(f"No results files found in {responses_dir}")

    logger.info(f"Loading results from {len(results_files)} files...")

    all_results = []
    failed_requests = []
    total_input_tokens = 0
    total_output_tokens = 0

    for results_file in results_files:
        with open(results_file) as f:
            for line in f:
                if not line.strip():
                    continue
                result = json.loads(line)

                if result["result_type"] == "succeeded":
                    parsed = parse_response(result["content"])
                    all_results.append(
                        {
                            "id": result["custom_id"],
                            "sentiment": parsed["s"],
                            "confidence": parsed["c"],
                            "sentiment_player": parsed.get("p"),
                            "input_tokens": result["input_tokens"],
                            "output_tokens": result["output_tokens"],
                        }
                    )
                    total_input_tokens += result["input_tokens"]
                    total_output_tokens += result["output_tokens"]
                else:
                    failed_requests.append(result)

    logger.info(f"Loaded {len(all_results)} successful results")
    if failed_requests:
        logger.warning(f"Found {len(failed_requests)} failed requests")

    # Update state with token totals
    state["total_input_tokens"] = total_input_tokens
    state["total_output_tokens"] = total_output_tokens
    state["estimated_cost_usd"] = calculate_cost(
        total_input_tokens, total_output_tokens
    )

    # Create results DataFrame
    results_df = pl.DataFrame(all_results)

    # Load comments with lazy evaluation
    logger.info(f"Loading comments from {filtered_path}...")
    comments_df = pl.scan_ndjson(filtered_path).select(
        [
            pl.col("id"),
            pl.col("body"),
            pl.col("author"),
            pl.col("author_flair_text"),
            pl.col("author_flair_css_class"),
            pl.col("created_utc"),
            pl.col("score"),
            pl.col("mentioned_players"),
        ]
    )

    # Join results with comments
    logger.info("Joining results with comments...")
    results_count = len(all_results)
    joined_df = (
        comments_df.join(results_df.lazy(), on="id", how="inner")
        .rename({"id": "comment_id"})
        .select(OUTPUT_COLUMNS)
        .collect()
    )

    # Validate join didn't drop rows
    joined_count = len(joined_df)
    if joined_count < results_count:
        dropped = results_count - joined_count
        logger.warning(
            f"Join dropped {dropped} results "
            f"({dropped / results_count * 100:.1f}% - comments may be missing from filtered file)"
        )

    logger.info(f"Final DataFrame: {joined_count} rows")

    return joined_df, failed_requests


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
    args = parser.parse_args()

    # Setup paths
    batches_dir = get_batches_dir()
    state_path = batches_dir / STATE_FILENAME
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
                save_state(state, state_path)
            except RuntimeError as e:
                logger.error(f"Failed to download batch {batch['batch_num']}: {e}")

        pending = get_pending_batches(state)
        if pending:
            logger.info(f"{len(pending)} batch(es) still pending")
        else:
            logger.info("All batches completed!")

    else:
        # Poll until complete or timeout
        logger.info(f"Polling every {args.poll_interval}s (max {args.max_wait}s)...")
        completed = poll_until_complete(
            state, state_path, responses_dir, args.poll_interval, args.max_wait
        )
        if not completed:
            logger.warning("Exiting with pending batches due to timeout")

    # Check if we can build the final output
    pending = get_pending_batches(state)
    not_downloaded = [
        b for b in state.get("batches", []) if not b.get("results_downloaded", False)
    ]

    if pending or not_downloaded:
        logger.info(
            f"Cannot build final output: {len(pending)} pending, "
            f"{len(not_downloaded)} not downloaded"
        )
        sys.exit(0)

    # Build final sentiment.parquet
    logger.info("=" * 60)
    logger.info("Building sentiment.parquet...")
    logger.info("=" * 60)

    try:
        sentiment_df, failed_requests = build_sentiment_dataframe(
            responses_dir, filtered_path, state
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
        save_state(state, state_path)
        logger.info("=" * 60)
        logger.info("Summary")
        logger.info("=" * 60)
        logger.info(f"Total input tokens:  {state['total_input_tokens']:,}")
        logger.info(f"Total output tokens: {state['total_output_tokens']:,}")
        logger.info(f"Estimated cost:      ${state['estimated_cost_usd']:.2f}")

    except FileNotFoundError as e:
        logger.error(f"Missing file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to build output: {e}")
        raise


if __name__ == "__main__":
    main()
