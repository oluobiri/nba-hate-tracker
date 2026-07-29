"""
Fetch and cache the season roster snapshot from stats.nba.com.

Writes data/<season>/reference/rosters.parquet — the reference asset the
Player-dimension build joins factual fields from. Refuses to overwrite an
existing snapshot unless --force: replacing a snapshot is a deliberate
act, so archive the old file first if it should survive.

Usage:
    uv run python -m scripts.fetch_rosters
    uv run python -m scripts.fetch_rosters --season 2024-25
    uv run python -m scripts.fetch_rosters --force
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from pipeline.nba_stats import fetch_rosters
from pipeline.schemas import ROSTERS_SCHEMA, SCHEMA_VERSION, validate_schema
from utils.paths import get_reference_dir
from utils.season_config import get_active_season, set_season_override

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

OUTPUT_FILENAME = "rosters.parquet"


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for roster snapshot fetching."""
    parser = argparse.ArgumentParser(
        description="Fetch and cache the season roster snapshot from stats.nba.com"
    )
    parser.add_argument(
        "--season",
        default=None,
        metavar="YYYY-YY",
        help='Override the active season (e.g. "2024-25"); the roster '
        "endpoint query and the output path both resolve to it for this run",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing snapshot",
    )
    args = parser.parse_args()

    if args.season:
        set_season_override(args.season)

    # Resolves after the override: one source for both the endpoint
    # season parameter and the season-scoped output directory.
    season = get_active_season()
    output_path = get_reference_dir() / OUTPUT_FILENAME

    if output_path.exists() and not args.force:
        logger.error(
            f"{output_path} already exists - move it aside to archive it, "
            "or pass --force to overwrite"
        )
        sys.exit(1)

    logger.info("=" * 60)
    logger.info(f"Roster snapshot: {season}")
    logger.info("=" * 60)

    rosters = fetch_rosters(season)
    validate_schema(rosters, ROSTERS_SCHEMA, OUTPUT_FILENAME)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Lineage metadata: a snapshot must carry its own fetch date and
    # season to stay diffable against later re-fetches.
    rosters.write_parquet(
        output_path,
        metadata={
            "season": season,
            "fetched_at": datetime.now(timezone.utc).date().isoformat(),
            "schema_version": str(SCHEMA_VERSION),
        },
    )

    logger.info(
        f"Wrote {rosters.height} players / "
        f"{rosters['team_abbr'].n_unique()} teams to {output_path}"
    )


if __name__ == "__main__":
    main()
