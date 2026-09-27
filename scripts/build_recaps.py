"""
Curation tools for the recaps: the candidate scan and an in-memory dry run.

The recaps themselves are built and written by scripts.aggregate_sentiment,
the one writer of the manifest. This script serves curation: --scan ranks
every (game, player) with a live thread by the swing in his negative share
and writes the report under reference/ (never published); --dry-run builds
every recap in recaps.yaml in memory and reports its alignment error,
stint reconciliation, sizes and counts, writing nothing. Both read the
dashboard tables an aggregate run produced.

Usage:
    uv run python -m scripts.build_recaps --season 2025-26 --scan
    uv run python -m scripts.build_recaps --season 2025-26 --dry-run
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from pipeline.aggregation import (
    classifier_identities,
    load_fact_subset,
    read_classifier_stamps,
)
from pipeline.lineage import OUTPUT_CONFIGS, config_versions
from pipeline.posts import GAME_THREAD
from pipeline.recaps import (
    RecapStamps,
    build_recap,
    encode_recap,
    resolve_recap_specs,
    scan_candidates,
)
from pipeline.nba_stats import load_play_by_play
from utils.constants import RECAP_CANDIDATES_FILENAME
from utils.paths import (
    get_dashboard_dir,
    get_play_by_play_dir,
    get_processed_dir,
    get_reference_dir,
)
from utils.recaps_config import load_recaps_config
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

FACT_FILENAME = "sentiment.parquet"
TABLES = ("players", "games", "player_games", "posts")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def load_tables(dashboard_dir: Path) -> dict[str, pl.DataFrame]:
    """
    Read the dashboard tables the recaps resolve against.

    Args:
        dashboard_dir: The season's dashboard directory.

    Returns:
        Table name -> frame for TABLES.

    Raises:
        FileNotFoundError: If any table is missing; the aggregate has
            not run for the season.
    """
    return {name: pl.read_parquet(dashboard_dir / f"{name}.parquet") for name in TABLES}


def main() -> None:
    """Main entry point for the recap curation tools."""
    parser = argparse.ArgumentParser(
        description="Recap curation: the candidate scan or an in-memory dry run"
    )
    parser.add_argument(
        "--season",
        default=None,
        metavar="YYYY-YY",
        help='Override the active season (e.g. "2024-25"); every path resolves '
        "to it for this run",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--scan",
        action="store_true",
        help="Rank every (game, player) with a live thread by swing; write the "
        "report under reference/",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Build every curated recap in memory and report on it; write nothing",
    )
    args = parser.parse_args()

    if args.season:
        set_season_override(args.season)

    season = get_active_season()
    fact_path = get_processed_dir() / FACT_FILENAME
    dashboard_dir = get_dashboard_dir()
    pbp_dir = get_play_by_play_dir()
    if not fact_path.exists():
        logger.error(f"{fact_path} not found")
        sys.exit(1)
    try:
        tables = load_tables(dashboard_dir)
    except FileNotFoundError as e:
        logger.error(f"{e.filename} not found - run scripts.aggregate_sentiment first")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info(f"Recaps: {season} ({'scan' if args.scan else 'dry run'})")
    logger.info(f"  fact:     {fact_path}")
    logger.info(f"  tables:   {dashboard_dir}")
    logger.info(f"  archive:  {pbp_dir}")
    logger.info("=" * 60)

    if args.scan:
        _scan(fact_path, tables, pbp_dir)
    else:
        _dry_run(fact_path, tables, pbp_dir, season)


def _scan(fact_path: Path, tables: dict[str, pl.DataFrame], pbp_dir: Path) -> None:
    """Write the candidate report: the Player x Game x Period grain, ranked."""
    posts = tables["posts"]
    thread_ids = posts.filter(pl.col("post_type") == GAME_THREAD)["post_id"].to_list()
    fact = load_fact_subset(fact_path, thread_ids)
    candidates, skipped = scan_candidates(
        fact, posts, tables["games"], tables["players"], pbp_dir
    )
    out = get_reference_dir() / RECAP_CANDIDATES_FILENAME
    candidates.write_csv(out)
    logger.info("=" * 60)
    logger.info(f"Wrote {out}: {candidates.height:,} candidates")
    if skipped:
        logger.warning(f"Skipped {len(skipped)} games without a usable archive")
    for row in candidates.head(10).rows(named=True):
        logger.info(
            f"  {row['game_id']}  {row['attributed_player']:<24} "
            f"n={row['live_n']:<6} swing={row['swing']:+.3f}"
        )
    logger.info("=" * 60)


def _dry_run(
    fact_path: Path, tables: dict[str, pl.DataFrame], pbp_dir: Path, season: str
) -> None:
    """Build every curated recap in memory and report; write nothing."""
    resolved = resolve_recap_specs(
        load_recaps_config(),
        tables["games"],
        tables["players"],
        tables["posts"],
        pbp_dir,
    )
    link_ids = [post_id for spec in resolved for post_id in spec.thread_ids]
    fact = load_fact_subset(fact_path, link_ids)
    versions = config_versions()
    stamps = RecapStamps(
        season=season,
        generated_at=datetime.now(timezone.utc).isoformat(),
        config_versions={name: versions[name] for name in OUTPUT_CONFIGS["recaps"]},
        classifiers=classifier_identities(read_classifier_stamps(fact_path)),
    )
    logger.info("=" * 60)
    for spec in resolved:
        doc = build_recap(
            spec,
            fact=fact,
            posts=tables["posts"],
            games=tables["games"],
            player_games=tables["player_games"],
            pbp=load_play_by_play(spec.pbp_path, log=logger),
            stamps=stamps,
        )
        entry = doc.entry
        error = (
            "unmeasured"
            if entry["error_seconds"] is None
            else f"{entry['error_seconds']} s"
        )
        logger.info(
            f"{doc.key}: live_n={entry['live_n']:,} room_n={entry['room_n']:,} "
            f"error={error} minutes_diff={entry['minutes_diff']:+d} "
            f"swing={entry['swing']:+.3f} bytes={len(encode_recap(doc)):,}"
        )
    logger.info(f"Dry run - {len(resolved)} recaps built, nothing written")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
