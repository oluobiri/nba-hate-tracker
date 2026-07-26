"""
Drive the full batch classification run: submit, poll, collect, repeat.

Replaces the v1 run_batches.sh loop. Keeps its serial one-batch-in-flight
behavior, but resolves paths per season, discovers the batch count from
the requests directory, and reads state through pipeline.batch helpers
instead of jq. Submission and collection run as subprocesses so their
fail-fast exit codes propagate; loop decisions are made in-process.

Usage:
    # Drive the active season's run, checking every 30 minutes
    uv run python -m scripts.run_batches

    # Faster cadence, explicit season
    uv run python -m scripts.run_batches --season 2025-26 --sleep-interval 600

Input: data/<season>/batches/requests/batch_NNN.jsonl, state.json
Output: exit 0 when all batches complete (final collect builds
    sentiment.parquet); exit 1 when a batch fails terminally.
"""

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from pipeline.batch import (
    DEFAULT_MAX_RETRIES,
    REQUESTS_SUBDIR,
    STATE_FILENAME,
    get_exhausted_batches,
    get_pending_batches,
    get_retryable_batches,
    get_unsubmitted_request_files,
    load_state,
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
# Subprocess steps
# -----------------------------------------------------------------------------


def run_step(module: str, extra_args: list[str], season: str | None) -> int:
    """
    Run a pipeline script as a subprocess, forwarding the season override.

    Args:
        module: Module path for python -m (e.g. "scripts.collect_results").
        extra_args: Additional CLI arguments for the script.
        season: Season override to forward, or None for the active season.

    Returns:
        The subprocess's exit code.
    """
    cmd = [sys.executable, "-m", module, *extra_args]
    if season:
        cmd += ["--season", season]
    logger.info(f"Running: {' '.join(cmd[2:])}")
    return subprocess.run(cmd).returncode


# -----------------------------------------------------------------------------
# Orchestration loop
# -----------------------------------------------------------------------------


def run_loop(
    state_path: Path,
    requests_dir: Path,
    season: str | None,
    sleep_interval: int,
    max_retries: int,
    retry_enabled: bool,
) -> int:
    """
    Alternate collect and submit until the run completes or fails.

    One batch in flight at a time, matching the v1 shell loop: submit
    only when nothing is processing, then wait out the processing window.

    Args:
        state_path: Path to the batch state file.
        requests_dir: Directory containing batch_NNN.jsonl request files.
        season: Season override to forward to subprocesses.
        sleep_interval: Seconds to wait between iterations.
        max_retries: Retry cap forwarded to submit_batches.
        retry_enabled: If False, forward --no-retry to submit_batches.

    Returns:
        Exit code: 0 when all batches completed, 1 on terminal failure.
    """
    submit_args = ["--batches", "1", "--max-retries", str(max_retries)]
    if not retry_enabled:
        submit_args.append("--no-retry")

    while True:
        batch_files = sorted(requests_dir.glob("batch_*.jsonl"))
        if not batch_files:
            logger.error(f"No batch files found in {requests_dir}")
            return 1

        state = load_state(state_path)

        # Refresh statuses and download completed batches
        if state.get("batches"):
            returncode = run_step(
                "scripts.collect_results", ["--no-wait"], season
            )
            if returncode != 0:
                # Safe mid-run: with --no-wait, collect only exits nonzero on
                # precondition checks, never after downloading data
                logger.warning(f"collect_results exited {returncode}; continuing")
            state = load_state(state_path)

        if get_exhausted_batches(state, max_retries):
            logger.error(
                "Batch(es) failed after exhausting retries - stopping. "
                "See state.json and the Anthropic console."
            )
            return 1

        pending = get_pending_batches(state)
        retryable = get_retryable_batches(state, max_retries)
        all_submitted = not get_unsubmitted_request_files(state, requests_dir)

        if not pending:
            if all_submitted and not retryable:
                logger.info("All batches complete!")
                return 0
            if all_submitted and retryable and not retry_enabled:
                logger.error(
                    f"--no-retry: {len(retryable)} wholesale-failed batch(es) "
                    f"left unretried - run is incomplete"
                )
                return 1

            returncode = run_step("scripts.submit_batches", submit_args, season)
            if returncode != 0:
                logger.error(
                    f"submit_batches exited {returncode} - stopping the loop"
                )
                return 1
            state = load_state(state_path)
            pending = get_pending_batches(state)

        logger.info(
            f"Progress: {len(state.get('batches', []))}/{len(batch_files)} "
            f"submitted, {len(pending)} processing"
        )
        logger.info(f"Sleeping {sleep_interval}s...")
        time.sleep(sleep_interval)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point with CLI argument handling."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Drive the batch classification run end to end"
    )
    parser.add_argument(
        "--sleep-interval",
        type=int,
        default=1800,
        metavar="N",
        help="Seconds between loop iterations (default: 1800 = 30 min)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        metavar="N",
        help=f"Retry cap forwarded to submit_batches "
        f"(default: {DEFAULT_MAX_RETRIES})",
    )
    parser.add_argument(
        "--no-retry",
        action="store_true",
        help="Forward --no-retry to submit_batches",
    )
    parser.add_argument(
        "--season",
        default=None,
        metavar="YYYY-YY",
        help='Override the active season (e.g. "2024-25"); forwarded to '
        "all subprocess steps",
    )
    args = parser.parse_args()

    if args.season:
        set_season_override(args.season)

    batches_dir = get_batches_dir()
    state_path = batches_dir / STATE_FILENAME
    requests_dir = batches_dir / REQUESTS_SUBDIR

    logger.info("=" * 60)
    logger.info("Batch Run Orchestrator")
    logger.info("=" * 60)
    logger.info(f"Requests dir:   {requests_dir}")
    logger.info(f"State file:     {state_path}")
    logger.info(f"Sleep interval: {args.sleep_interval}s")
    logger.info("=" * 60)

    try:
        exit_code = run_loop(
            state_path=state_path,
            requests_dir=requests_dir,
            season=args.season,
            sleep_interval=args.sleep_interval,
            max_retries=args.max_retries,
            retry_enabled=not args.no_retry,
        )
    except KeyboardInterrupt:
        logger.warning("Interrupted - subprocesses save their own state; exiting")
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
