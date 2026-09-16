"""
Build the Post bridge from the raw posts download.

Writes data/<season>/reference/posts_bridge.parquet: every post with
its post_type and game_id, resolved against the Game dimension built
from the season's team game-log snapshot. Aggregation publishes the
subset it needs from here. Refuses to overwrite an existing bridge
unless --force.

Usage:
    uv run python -m scripts.process_posts
    uv run python -m scripts.process_posts --season 2024-25
    uv run python -m scripts.process_posts --force
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

import polars as pl

from pipeline.games import TEAM_GAME_LOG_FILENAME, build_games
from pipeline.lineage import config_stamps
from pipeline.nba_stats import check_snapshot_season
from pipeline.posts import (
    POSTS_BRIDGE_FILENAME,
    RAW_POSTS_FILENAME,
    build_posts_bridge,
    read_raw_posts,
)
from pipeline.schemas import POSTS_SCHEMA, SCHEMA_VERSION, validate_schema
from utils.paths import get_raw_dir, get_reference_dir
from utils.season_config import get_active_season, set_season_override
from utils.team_config import load_team_config

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
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for building the Post bridge."""
    parser = argparse.ArgumentParser(
        description="Build the Post bridge (post_type, game_id) from the raw posts"
    )
    parser.add_argument(
        "--season",
        default=None,
        metavar="YYYY-YY",
        help='Override the active season (e.g. "2024-25"); the input and '
        "output paths both resolve to it for this run",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing bridge",
    )
    args = parser.parse_args()

    if args.season:
        set_season_override(args.season)

    season = get_active_season()
    reference_dir = get_reference_dir()
    raw_path = get_raw_dir() / RAW_POSTS_FILENAME
    team_log_path = reference_dir / TEAM_GAME_LOG_FILENAME
    bridge_path = reference_dir / POSTS_BRIDGE_FILENAME

    if not raw_path.exists():
        logger.error(f"{raw_path} not found - run scripts.download_posts first")
        sys.exit(1)
    if not team_log_path.exists():
        logger.error(f"{team_log_path} not found - run scripts.fetch_games first")
        sys.exit(1)
    if bridge_path.exists() and not args.force:
        logger.error(
            f"{bridge_path} already exists - move it aside to archive it, "
            "or pass --force to overwrite"
        )
        sys.exit(1)

    logger.info("=" * 60)
    logger.info(f"Post bridge: {season}")
    logger.info("=" * 60)

    team_stamps = check_snapshot_season(team_log_path, subject="game data", log=logger)
    team_config = load_team_config()
    abbr_to_team = {info["abbreviation"]: team for team, info in team_config.items()}
    games = build_games(pl.read_parquet(team_log_path), abbr_to_team)

    posts = read_raw_posts(raw_path)
    bridge = build_posts_bridge(posts, games, team_config)
    validate_schema(bridge, POSTS_SCHEMA, POSTS_BRIDGE_FILENAME)

    # Lineage metadata: the bridge is a derivation, so it names the
    # snapshot and config it was derived under, not a fetch date.
    stamps = {
        "season": season,
        "processed_at": datetime.now(timezone.utc).date().isoformat(),
        **config_stamps("posts_bridge"),
        "schema_version": str(SCHEMA_VERSION),
    }
    if team_stamps.get("fetched_at") is not None:
        stamps["games_fetched_at"] = team_stamps["fetched_at"]
    reference_dir.mkdir(parents=True, exist_ok=True)
    bridge.write_parquet(bridge_path, metadata=stamps)

    logger.info(f"Wrote {bridge.height} posts to {bridge_path}")


if __name__ == "__main__":
    main()
