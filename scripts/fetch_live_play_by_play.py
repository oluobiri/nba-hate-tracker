"""
Bank every game's live play-by-play from cdn.nba.com as per-game snapshots.

Writes data/<season>/reference/play_by_play_live/<game_id>.parquet, one
file per game the games table keeps, derived from the banked team game
log (run scripts.fetch_games first). Resumable: a game with a valid file
on disk is skipped, so a killed run picks up where it stopped. Misses
are reported at the end and make the exit code non-zero; a re-run
retries only them. A run the CDN keeps refusing stops early and says
how many games it never requested. --dry-run prints the plan and makes
no request.

Usage:
    uv run python -m scripts.fetch_live_play_by_play --dry-run
    uv run python -m scripts.fetch_live_play_by_play
    uv run python -m scripts.fetch_live_play_by_play --season 2024-25
"""

import argparse
import logging
import sys

from pipeline.games import TEAM_GAME_LOG_FILENAME, load_game_ids
from pipeline.nba_stats import (
    has_valid_live_play_by_play,
    play_by_play_path,
    sync_live_play_by_play,
)
from utils.paths import get_live_play_by_play_dir, get_reference_dir
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
    """Main entry point for the live play-by-play archive."""
    parser = argparse.ArgumentParser(
        description="Bank every game's liveData play-by-play from cdn.nba.com, "
        "one file per game"
    )
    parser.add_argument(
        "--season",
        default=None,
        metavar="YYYY-YY",
        help='Override the active season (e.g. "2024-25"); the game list and '
        "the output path both resolve to it for this run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan (games, already banked, to fetch) and make no request",
    )
    args = parser.parse_args()

    if args.season:
        set_season_override(args.season)

    season = get_active_season()
    team_path = get_reference_dir() / TEAM_GAME_LOG_FILENAME
    out_dir = get_live_play_by_play_dir()
    if not team_path.exists():
        logger.error(f"{team_path} not found - run scripts.fetch_games first")
        sys.exit(1)

    game_ids = load_game_ids(team_path, load_team_config(), log=logger)
    banked = sum(
        has_valid_live_play_by_play(play_by_play_path(out_dir, g)) for g in game_ids
    )

    logger.info("=" * 60)
    logger.info(
        f"Live play-by-play archive: {season}{' (DRY RUN)' if args.dry_run else ''}"
    )
    logger.info(
        f"  games:  {len(game_ids)} ({banked} banked, {len(game_ids) - banked} to fetch)"
    )
    logger.info(f"  to:     {out_dir}")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("Dry run - nothing fetched")
        return

    report = sync_live_play_by_play(game_ids, out_dir, season=season)

    logger.info("=" * 60)
    logger.info(
        f"Fetched {len(report.fetched)}, skipped {len(report.skipped)} already "
        f"banked, {len(report.misses)} misses, {len(report.unrequested)} not requested"
    )
    if not report.ok:
        for miss in report.misses:
            logger.error(f"  miss  {miss.game_id}: {miss.reason}")
        if report.unrequested:
            logger.error(
                f"Stopped on refusals with {len(report.unrequested)} games not "
                f"requested; wait before running again"
            )
        logger.error("Re-run to retry only what is not banked")
        sys.exit(1)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
