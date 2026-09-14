"""
Aggregate sentiment data into the published tables.

Reads classified sentiment parquet, computes player rankings, flair
segmentation, temporal trends, the game layer and the receipts. Writes
one parquet per produced table (the fact views, the players and teams
dimensions, the game layer, and the comment_samples fact subset) plus
manifest.json, the metadata block, into the season's dashboard
directory for ad-hoc DuckDB queries and the v2 frontend.

Usage:
    uv run python -m scripts.aggregate_sentiment
    uv run python -m scripts.aggregate_sentiment --input data/processed/sentiment.parquet --output-dir data/dashboard
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from pipeline.aggregation import aggregate_sentiment
from pipeline.receipts import samples_stamps
from pipeline.schemas import DASHBOARD_OUTPUT_SCHEMAS, SCHEMA_VERSION
from utils.paths import get_dashboard_dir, get_processed_dir
from utils.player_config import load_player_config_version
from utils.season_config import set_season_override
from utils.team_config import load_team_config_version

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
# Default filenames (directories come from utils/paths)
# -----------------------------------------------------------------------------

DEFAULT_INPUT_FILENAME = "sentiment.parquet"
DEFAULT_TARGETS_FILENAME = "sentiment_targets.parquet"
MANIFEST_FILENAME = "manifest.json"


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for sentiment aggregation."""
    parser = argparse.ArgumentParser(
        description="Aggregate sentiment data into the published tables"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to sentiment parquet file "
        f"(default: data/<season>/processed/{DEFAULT_INPUT_FILENAME})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write the parquet tables and manifest.json "
        "(default: data/<season>/dashboard)",
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=None,
        help="Path to the target-verifier sidecar; absent file -> gate-only "
        f"samples (default: data/<season>/processed/{DEFAULT_TARGETS_FILENAME})",
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

    # Defaults resolve after the season override so they land in the
    # right season directory
    input_path = args.input or get_processed_dir() / DEFAULT_INPUT_FILENAME
    targets_path = args.targets or get_processed_dir() / DEFAULT_TARGETS_FILENAME
    output_dir = args.output_dir or get_dashboard_dir()

    # Validate input exists
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    # Log configuration
    logger.info("=" * 60)
    logger.info("Sentiment Aggregation")
    logger.info("=" * 60)
    logger.info(f"Input:   {input_path}")
    logger.info(f"Targets: {targets_path}")
    logger.info(f"Output:  {output_dir}")
    logger.info("=" * 60)

    # Pre-flight the config-version stamps before anything runs or is
    # written: a bad config version (e.g. an unquoted YAML float) must
    # abort here, never between output writes — a torn output set
    # (fresh dimensions beside stale views) is exactly the inconsistency
    # the stamps exist to make detectable.
    stamps: dict[str, dict[str, str]] = {
        "players": {"players_config_version": load_player_config_version()},
        "teams": {"teams_config_version": load_team_config_version()},
    }

    # Run aggregation
    result = aggregate_sentiment(input_path, targets_path)
    # The samples stamp is read back from the sidecar inside aggregation
    # (verified flag + verifier identity), so it joins the set here
    stamps["comment_samples"] = samples_stamps(result["metadata"])
    # The game tables carry their snapshot's fetch date forward (None
    # when no snapshot was on disk and the tables are empty)
    game_stamps = {}
    if result["metadata"]["games_fetched_at"] is not None:
        game_stamps["fetched_at"] = result["metadata"]["games_fetched_at"]
    stamps["games"] = stamps["player_games"] = game_stamps
    # The Post bridge carries its build date forward the same way
    posts_stamps = {}
    if result["metadata"]["posts_processed_at"] is not None:
        posts_stamps["processed_at"] = result["metadata"]["posts_processed_at"]
    stamps["posts"] = posts_stamps

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write one parquet per produced table. Every file carries the
    # contract version; each dimension adds the config-version stamp
    # pre-flighted above, so fact<->dimension drift is checkable (same
    # mechanism as sentiment.parquet's stamp in collect_results);
    # comment_samples adds its verified flag and verifier identity; the
    # game tables their snapshot's fetch date, posts its build date.
    version_stamp = {"schema_version": str(SCHEMA_VERSION)}
    for name in DASHBOARD_OUTPUT_SCHEMAS:
        parquet_path = output_dir / f"{name}.parquet"
        result[name].write_parquet(
            parquet_path, metadata={**version_stamp, **stamps.get(name, {})}
        )
        logger.info(f"Wrote {parquet_path}")

    # Write the metadata block as manifest.json. Seeded verbatim; the
    # manifest's published shape (identity, semantic layer, season facts,
    # table registry) is built up in place from here — don't type
    # consumers against this seed.
    manifest_path = output_dir / MANIFEST_FILENAME
    with open(manifest_path, "w") as f:
        json.dump(result["metadata"], f, indent=2, default=str)
    logger.info(f"Wrote {manifest_path}")

    # Log metadata summary
    meta = result["metadata"]
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    logger.info(f"Total comments:      {meta['total_comments']:,}")
    logger.info(f"Usable comments:     {meta['usable_comments']:,}")
    logger.info(f"Excluded (errors):   {meta['excluded_comments']:,}")
    logger.info(f"Attributed:          {meta['attributed_comments']:,}")
    logger.info(f"Players:             {meta['player_count']}")
    logger.info(f"Teams:               {meta['team_count']}")
    logger.info(f"Weeks:               {meta['week_count']}")
    logger.info(f"Games:               {meta['game_count']:,}")
    logger.info(f"Player-game lines:   {meta['player_game_count']:,}")
    logger.info(f"Posts:               {meta['post_count']:,}")
    logger.info(f"Receipts verified:   {meta['receipts_verified']}")
    # Both are None in the fallback; precision is also None when no
    # would-have-shipped row carries a verdict
    if meta["receipts_coverage"] is not None:
        logger.info(f"Receipts coverage:   {meta['receipts_coverage']:.1%}")
    if meta["receipts_precision"] is not None:
        logger.info(f"Receipts precision:  {meta['receipts_precision']:.1%}")


if __name__ == "__main__":
    main()
