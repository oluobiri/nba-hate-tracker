"""
Fetch and cache the season game-log snapshots from stats.nba.com.

Writes data/<season>/reference/team_game_log.parquet and
player_game_log.parquet — the reference assets the games and
player_games tables derive from at aggregation. Refuses to overwrite
existing snapshots unless --force: replacing a snapshot is a deliberate
act, so archive the old files first if they should survive.

Usage:
    uv run python -m scripts.fetch_games
    uv run python -m scripts.fetch_games --season 2024-25
    uv run python -m scripts.fetch_games --force
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from pipeline.games import PLAYER_GAME_LOG_FILENAME, TEAM_GAME_LOG_FILENAME
from pipeline.nba_stats import fetch_player_game_log, fetch_team_game_log
from pipeline.schemas import (
    PLAYER_GAME_LOG_SCHEMA,
    SCHEMA_VERSION,
    TEAM_GAME_LOG_SCHEMA,
    validate_schema,
)
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
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for game-log snapshot fetching."""
    parser = argparse.ArgumentParser(
        description="Fetch and cache the season game-log snapshots from stats.nba.com"
    )
    parser.add_argument(
        "--season",
        default=None,
        metavar="YYYY-YY",
        help='Override the active season (e.g. "2024-25"); the endpoint '
        "query and the output path both resolve to it for this run",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing snapshots",
    )
    args = parser.parse_args()

    if args.season:
        set_season_override(args.season)

    # Resolves after the override: one source for both the endpoint
    # season parameter and the season-scoped output directory.
    season = get_active_season()
    reference_dir = get_reference_dir()
    team_path = reference_dir / TEAM_GAME_LOG_FILENAME
    player_path = reference_dir / PLAYER_GAME_LOG_FILENAME

    existing = [p for p in (team_path, player_path) if p.exists()]
    if existing and not args.force:
        logger.error(
            f"{[str(p) for p in existing]} already exist - move them aside to "
            "archive them, or pass --force to overwrite"
        )
        sys.exit(1)

    logger.info("=" * 60)
    logger.info(f"Game-log snapshots: {season}")
    logger.info("=" * 60)

    # Both logs fetch before either writes, so a failed player fetch
    # never leaves a fresh team log beside a stale player log.
    team_log = fetch_team_game_log(season)
    validate_schema(team_log, TEAM_GAME_LOG_SCHEMA, TEAM_GAME_LOG_FILENAME)
    player_log = fetch_player_game_log(season)
    validate_schema(player_log, PLAYER_GAME_LOG_SCHEMA, PLAYER_GAME_LOG_FILENAME)

    # Lineage metadata: a snapshot must carry its own fetch date and
    # season to stay diffable against later re-fetches.
    stamps = {
        "season": season,
        "fetched_at": datetime.now(timezone.utc).date().isoformat(),
        "schema_version": str(SCHEMA_VERSION),
    }
    reference_dir.mkdir(parents=True, exist_ok=True)
    team_log.write_parquet(team_path, metadata=stamps)
    player_log.write_parquet(player_path, metadata=stamps)

    logger.info(
        f"Wrote {team_log.height} team lines / "
        f"{team_log['game_id'].n_unique()} games to {team_path}"
    )
    logger.info(
        f"Wrote {player_log.height} player lines / "
        f"{player_log['player_id'].n_unique()} players to {player_path}"
    )


if __name__ == "__main__":
    main()
