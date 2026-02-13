"""
Export bar race CSV for Flourish from aggregates.json.

Reads precomputed weekly sentiment aggregates, computes cumulative
negative-sentiment rates, and pivots into the wide CSV format that
Flourish's bar chart race template expects.

Usage:
    uv run python -m scripts.export_bar_race
    uv run python -m scripts.export_bar_race --top-n 20 --min-ranking-comments 3000 --min-entry-comments 500
    uv run python -m scripts.export_bar_race --input data/dashboard/aggregates.json --output data/dashboard/bar_race.csv
"""

import argparse
import json
import logging
import sys
from pathlib import Path

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

DEFAULT_INPUT_FILENAME = "aggregates.json"
DEFAULT_OUTPUT_FILENAME = "bar_race.csv"


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for bar race CSV export."""
    default_input = get_dashboard_dir() / DEFAULT_INPUT_FILENAME
    default_output = get_dashboard_dir() / DEFAULT_OUTPUT_FILENAME

    parser = argparse.ArgumentParser(
        description="Export bar race CSV for Flourish from aggregates.json"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help=f"Path to aggregates JSON file (default: {default_input})",
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
    input_path = args.input or default_input
    output_path = args.output or default_output

    # Validate input exists
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    # Log configuration
    logger.info("=" * 60)
    logger.info("Bar Race CSV Export")
    logger.info("=" * 60)
    logger.info(f"Input:  {input_path}")
    logger.info(f"Output: {output_path}")
    logger.info(f"Top N:  {args.top_n}")
    logger.info(f"Min ranking comments: {args.min_ranking_comments}")
    logger.info(f"Min entry comments:   {args.min_entry_comments}")
    logger.info("=" * 60)

    # Load aggregates
    with open(input_path) as f:
        data = json.load(f)

    # Transform
    cumulative = compute_cumulative_metrics(data["player_temporal"])
    logger.info(
        f"Computed cumulative metrics: {cumulative['attributed_player'].n_unique()} "
        f"players x {cumulative['week'].n_unique()} weeks"
    )

    wide = pivot_bar_race_wide(
        cumulative, data["player_metadata"],
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
