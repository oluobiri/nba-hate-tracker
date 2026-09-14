"""
Export bar race CSV for Flourish from the dashboard parquet tables.

Reads player_temporal.parquet and players.parquet, computes cumulative
negative-sentiment rates, and pivots into the wide CSV format that
Flourish's bar chart race template expects.

Usage:
    uv run python -m scripts.export_bar_race
    uv run python -m scripts.export_bar_race --top-n 20 --min-ranking-comments 3000 --min-entry-comments 500
    uv run python -m scripts.export_bar_race --input-dir data/2025-26/dashboard --output data/2025-26/dashboard/bar_race.csv
"""

import argparse
import logging
import sys
from pathlib import Path

import polars as pl

from pipeline.aggregation import (
    compute_cumulative_metrics,
    pivot_bar_race_wide,
)
from utils.paths import get_dashboard_dir

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

TEMPORAL_FILENAME = "player_temporal.parquet"
PLAYERS_FILENAME = "players.parquet"
DEFAULT_OUTPUT_FILENAME = "bar_race.csv"


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for bar race CSV export."""
    default_input_dir = get_dashboard_dir()
    default_output = default_input_dir / DEFAULT_OUTPUT_FILENAME

    parser = argparse.ArgumentParser(
        description="Export bar race CSV for Flourish from the dashboard parquet tables"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help=f"Dashboard directory holding the parquet tables (default: {default_input_dir})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Path to write bar race CSV (default: {default_output})",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=15,
        help="Number of top players to include (default: 15)",
    )
    parser.add_argument(
        "--min-ranking-comments",
        type=int,
        default=5000,
        help="Minimum cumulative comments to qualify for top-N ranking (default: 5000)",
    )
    parser.add_argument(
        "--min-entry-comments",
        type=int,
        default=1000,
        help="Minimum cumulative comments for a player's bar to appear (default: 1000)",
    )
    args = parser.parse_args()

    # Apply defaults after parsing
    input_dir = args.input_dir or default_input_dir
    output_path = args.output or default_output
    temporal_path = input_dir / TEMPORAL_FILENAME
    players_path = input_dir / PLAYERS_FILENAME

    # Validate inputs exist
    for path in (temporal_path, players_path):
        if not path.exists():
            logger.error(f"Input file not found: {path}")
            sys.exit(1)

    # Log configuration
    logger.info("=" * 60)
    logger.info("Bar Race CSV Export")
    logger.info("=" * 60)
    logger.info(f"Input:  {input_dir}")
    logger.info(f"Output: {output_path}")
    logger.info(f"Top N:  {args.top_n}")
    logger.info(f"Min ranking comments: {args.min_ranking_comments}")
    logger.info(f"Min entry comments:   {args.min_entry_comments}")
    logger.info("=" * 60)

    # Load the two tables
    player_temporal = pl.read_parquet(temporal_path)
    players = pl.read_parquet(players_path)

    # Transform
    cumulative = compute_cumulative_metrics(player_temporal)
    logger.info(
        f"Computed cumulative metrics: {cumulative['attributed_player'].n_unique()} "
        f"players x {cumulative['week'].n_unique()} weeks"
    )

    wide = pivot_bar_race_wide(
        cumulative,
        players,
        top_n=args.top_n,
        min_ranking_comments=args.min_ranking_comments,
        min_entry_comments=args.min_entry_comments,
    )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write CSV
    wide.write_csv(output_path)

    # Summary
    week_cols = [c for c in wide.columns if c not in {"Label", "Category", "Image"}]
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    logger.info(f"Players: {wide.height}")
    logger.info(f"Weeks:   {len(week_cols)}")
    logger.info(f"Output:  {output_path}")


if __name__ == "__main__":
    main()
