"""
Prepare the target-verifier pool and its batch request files.

Reads the season's sentiment.parquet, selects the pool (top-k receipt
candidates per player x polar sentiment with the target gate lifted,
plus two random evidence strata), writes it as pool.parquet, and writes
one request per pool row for the target stage. Submit, collect, and
run_batches then take --stage target.

Usage:
    uv run python -m scripts.prepare_targets
    uv run python -m scripts.prepare_targets --season 2024-25 --k 30

Input: data/<season>/processed/sentiment.parquet
Output:
    - data/<season>/batches/target/pool.parquet
    - data/<season>/batches/target/requests/batch_NNN.jsonl
"""

import argparse
import logging
import sys


from pipeline.aggregation import load_attributed_frame
from pipeline.batch import (
    REQUESTS_PER_BATCH,
    REQUESTS_SUBDIR,
    format_batch_request,
    write_request_file,
)
from pipeline.receipts import build_target_pool
from pipeline.schemas import SCHEMA_VERSION
from pipeline.targets import TARGET_STAGE
from utils.constants import TARGET_POOL_K, TARGET_POOL_SEED, TARGET_POOL_STRATUM_N
from utils.paths import get_batches_dir, get_processed_dir
from utils.player_config import load_player_config_version
from utils.season_config import set_season_override

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

POOL_FILENAME = "pool.parquet"
SENTIMENT_FILENAME = "sentiment.parquet"


def main() -> None:
    """Main entry point with CLI argument handling."""
    parser = argparse.ArgumentParser(
        description="Prepare the target-verifier pool and batch request files"
    )
    parser.add_argument(
        "--k",
        type=int,
        default=TARGET_POOL_K,
        help=f"Candidate depth per player x sentiment cell (default: {TARGET_POOL_K})",
    )
    parser.add_argument(
        "--stratum-n",
        type=int,
        default=TARGET_POOL_STRATUM_N,
        help=f"Rows per random evidence stratum (default: {TARGET_POOL_STRATUM_N})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=TARGET_POOL_SEED,
        help=f"Sampling seed for the strata (default: {TARGET_POOL_SEED})",
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

    input_path = get_processed_dir() / SENTIMENT_FILENAME
    batches_dir = get_batches_dir(TARGET_STAGE.name)
    requests_dir = batches_dir / REQUESTS_SUBDIR
    pool_path = batches_dir / POOL_FILENAME

    if not input_path.exists():
        logger.error(f"Sentiment parquet not found: {input_path}")
        sys.exit(1)
    if pool_path.exists() or (
        requests_dir.exists() and any(requests_dir.glob("batch_*.jsonl"))
    ):
        logger.error(
            f"{batches_dir} already holds a pool or request files; remove the "
            f"stage directory to prepare a fresh one"
        )
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Prepare Target-Verifier Pool")
    logger.info("=" * 60)
    logger.info(
        f"Stage:    {TARGET_STAGE.name} ({TARGET_STAGE.model}, {TARGET_STAGE.prompt_version})"
    )
    logger.info(f"Input:    {input_path}")
    logger.info(f"Pool:     {pool_path}")
    logger.info(f"Requests: {requests_dir}")
    logger.info(f"k={args.k}, stratum_n={args.stratum_n}, seed={args.seed}")
    logger.info("=" * 60)

    df, _ = load_attributed_frame(input_path)
    pool = build_target_pool(df, k=args.k, stratum_n=args.stratum_n, seed=args.seed)

    # The pool's composition is a config-derived selection; stamp it like
    # the fact so drift is detectable at aggregation.
    batches_dir.mkdir(parents=True, exist_ok=True)
    pool.write_parquet(
        pool_path,
        metadata={
            "players_config_version": load_player_config_version(),
            "schema_version": str(SCHEMA_VERSION),
            "pool_k": str(args.k),
            "pool_stratum_n": str(args.stratum_n),
            "pool_seed": str(args.seed),
        },
    )
    logger.info(f"Wrote {pool.height:,} pool rows to {pool_path}")

    with_bodies = pool.join(
        df.select("comment_id", "body"),
        on="comment_id",
        how="left",
        maintain_order="left",
    )
    if with_bodies["body"].null_count():
        raise ValueError("pool rows without a body: the pool must come from this frame")
    requests = [
        format_batch_request(
            TARGET_STAGE,
            row["comment_id"],
            comment_body=row["body"],
            sentiment=row["sentiment"],
        )
        for row in with_bodies.iter_rows(named=True)
    ]
    batch_count = 0
    for start in range(0, len(requests), REQUESTS_PER_BATCH):
        batch_count += 1
        write_request_file(
            requests_dir, batch_count, requests[start : start + REQUESTS_PER_BATCH]
        )
    logger.info(
        f"Wrote {len(requests):,} requests across {batch_count} file(s) to {requests_dir}"
    )


if __name__ == "__main__":
    main()
