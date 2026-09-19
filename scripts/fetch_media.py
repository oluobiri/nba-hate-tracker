"""
Fetch headshots and logos from the league CDN and derive the WebP variants.

Writes data/media/headshots/<player_id>.png with its -180/-420/-840 WebP
siblings and data/media/logos/<team_id>.svg. Resumable: originals and
variants already on disk are left alone unless --force. Misses are
reported at the end and make the exit code non-zero; a re-run picks up
where the misses left off.

Ids come from the season's players.yaml (the active season's file is
the superset) and teams.yaml; the config URLs are checked against the
derived source URLs before any request. --dry-run prints the plan and
makes no request.

Usage:
    uv run python -m scripts.fetch_media --dry-run
    uv run python -m scripts.fetch_media
    uv run python -m scripts.fetch_media --season 2024-25
    uv run python -m scripts.fetch_media --force
"""

import argparse
import logging
import sys

from pipeline.media import MediaError, build_plan, sync_media, verify_config_urls
from utils.paths import get_media_dir
from utils.player_config import load_player_metadata
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
    """Main entry point for fetching media and deriving variants."""
    parser = argparse.ArgumentParser(
        description="Fetch headshots and logos from cdn.nba.com and derive WebP variants"
    )
    parser.add_argument(
        "--season",
        default=None,
        metavar="YYYY-YY",
        help='Override the active season (e.g. "2024-25"); its players.yaml '
        "supplies the player ids for this run",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refetch every original and regenerate every variant",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan (fetch, present, generate, up to date) and make no request",
    )
    args = parser.parse_args()

    if args.season:
        set_season_override(args.season)

    # Resolves after the override so the ids come from the requested season
    season = get_active_season()
    players = load_player_metadata()
    teams = load_team_config()
    media_dir = get_media_dir()

    try:
        verify_config_urls(players, teams)
    except MediaError as e:
        logger.error(f"Config check failed: {e}")
        sys.exit(1)

    player_ids = [meta["player_id"] for meta in players.values()]
    team_ids = [info["team_id"] for info in teams.values()]

    logger.info("=" * 60)
    logger.info(f"Media fetch{' (DRY RUN)' if args.dry_run else ''}")
    logger.info(f"  ids:  {len(player_ids)} players ({season}), {len(team_ids)} teams")
    logger.info(f"  to:   {media_dir}")
    logger.info("=" * 60)

    if args.dry_run:
        plan = build_plan(player_ids, team_ids, media_dir, force=args.force)
        logger.info(f"Plan for {media_dir}\n{plan.describe()}")
        logger.info("Dry run - nothing fetched")
        return

    report = sync_media(player_ids, team_ids, media_dir, force=args.force)

    logger.info("=" * 60)
    logger.info(
        f"Fetched {len(report.fetched)} originals, generated "
        f"{len(report.generated)} variants, {len(report.misses)} misses"
    )
    if not report.ok:
        for miss in report.misses:
            logger.error(f"  miss  {miss.name}: {miss.reason}")
        logger.error("Re-run to retry the misses; nothing present is refetched")
        sys.exit(1)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
