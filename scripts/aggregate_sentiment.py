"""
Aggregate sentiment data into dashboard-ready outputs.

Reads classified sentiment parquet, computes player rankings,
flair segmentation, and temporal trends. Writes the nested
aggregates.json for the Streamlit dashboard plus one parquet per
produced table (the four fact views, the players and teams
dimensions, and the comment_samples fact subset) alongside it for
ad-hoc DuckDB queries and the v2 frontend.

Usage:
    uv run python -m scripts.aggregate_sentiment
    uv run python -m scripts.aggregate_sentiment --input data/processed/sentiment.parquet --output data/dashboard/aggregates.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from pipeline.aggregation import aggregate_sentiment, players_to_metadata_dict
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
DEFAULT_OUTPUT_FILENAME = "aggregates.json"

# The legacy aggregates.json key set, frozen as a literal: exactly the
# record-shaped views the file carried when it was demoted to legacy.
# Deliberately NOT keyed off AGGREGATE_VIEW_SCHEMAS — that mapping grows
# with new fact views, and this list never does. New outputs of any kind
# are parquet-only; the file retires wholesale.
LEGACY_JSON_VIEWS = (
    "player_overall",
    "player_temporal",
    "player_team",
    "team_overall",
)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for sentiment aggregation."""
    parser = argparse.ArgumentParser(
        description="Aggregate sentiment data into dashboard-ready JSON"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to sentiment parquet file "
        f"(default: data/<season>/processed/{DEFAULT_INPUT_FILENAME})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write aggregates JSON "
        f"(default: data/<season>/dashboard/{DEFAULT_OUTPUT_FILENAME})",
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
    output_path = args.output or get_dashboard_dir() / DEFAULT_OUTPUT_FILENAME

    # Validate input exists
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    # Log configuration
    logger.info("=" * 60)
    logger.info("Sentiment Aggregation")
    logger.info("=" * 60)
    logger.info(f"Input:  {input_path}")
    logger.info(f"Output: {output_path}")
    logger.info("=" * 60)

    # Pre-flight the config-version stamps before anything runs or is
    # written: a bad config version (e.g. an unquoted YAML float) must
    # abort here, never between output writes — a torn output set
    # (fresh aggregates.json beside stale parquets) is exactly the
    # inconsistency the stamps exist to make detectable.
    stamps = {
        "players": {
            "players_config_version": load_player_config_version(),
            "schema_version": str(SCHEMA_VERSION),
        },
        "teams": {
            "teams_config_version": load_team_config_version(),
            "schema_version": str(SCHEMA_VERSION),
        },
    }

    # Run aggregation
    result = aggregate_sentiment(input_path)

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write JSON output — the LEGACY_JSON_VIEWS literal freezes the key
    # set: those views -> lists of dicts; the players dimension -> the
    # legacy nested player_metadata dict (consumer-safe shim); the
    # metadata scalar passes through. Anything else (the teams
    # dimension, any future output) is parquet-only.
    # default=str keeps week datetimes serialized exactly as before.
    serializable = {}
    for key, value in result.items():
        if key in LEGACY_JSON_VIEWS:
            serializable[key] = value.to_dicts()
        elif key == "players":
            serializable["player_metadata"] = players_to_metadata_dict(value)
        elif key == "metadata":
            serializable[key] = value
    with open(output_path, "w") as f:
        json.dump(serializable, f, indent=2, default=str)

    logger.info(f"Wrote aggregates to {output_path}")

    # Write one parquet per produced table (four views, the players and
    # teams dimensions, comment_samples). Each dimension carries the
    # config-version stamp pre-flighted above, so fact<->dimension drift
    # is checkable (same mechanism as sentiment.parquet's stamp in
    # collect_results); the other outputs carry none.
    for name in DASHBOARD_OUTPUT_SCHEMAS:
        parquet_path = output_path.parent / f"{name}.parquet"
        result[name].write_parquet(parquet_path, metadata=stamps.get(name))
        logger.info(f"Wrote {parquet_path}")

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


if __name__ == "__main__":
    main()
