"""
Aggregate sentiment data into dashboard-ready JSON.

Reads classified sentiment parquet, computes player rankings,
flair segmentation, and temporal trends. Outputs precomputed
aggregates for the Streamlit dashboard.

Usage:
    uv run python -m scripts.aggregate_sentiment
    uv run python -m scripts.aggregate_sentiment --input data/processed/sentiment.parquet --output data/dashboard/aggregates.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from pipeline.aggregation import aggregate_sentiment
from utils.paths import get_dashboard_dir, get_processed_dir

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


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for sentiment aggregation."""
    default_input = get_processed_dir() / DEFAULT_INPUT_FILENAME
    default_output = get_dashboard_dir() / DEFAULT_OUTPUT_FILENAME

    parser = argparse.ArgumentParser(
        description="Aggregate sentiment data into dashboard-ready JSON"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help=f"Path to sentiment parquet file (default: {default_input})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Path to write aggregates JSON (default: {default_output})",
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
    logger.info("Sentiment Aggregation")
    logger.info("=" * 60)
    logger.info(f"Input:  {input_path}")
    logger.info(f"Output: {output_path}")
    logger.info("=" * 60)

    # Run aggregation
    result = aggregate_sentiment(input_path)

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write JSON output
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    logger.info(f"Wrote aggregates to {output_path}")

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
