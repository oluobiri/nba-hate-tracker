"""
Publish the media drop (headshots and logos) to the public bucket.

Derives the upload set from every known season's dimension tables, never
from the media directory: exactly the originals, variants, and logos the
published ids imply. Pre-flights that every file is present, diffs the set
against the bucket, writes what changed, deletes keys the set no longer
names, invalidates the media path, and HEADs every public URL. A dry run
stops after the diff and prints the plan.

The AWS profile in config/publish.yaml assumes the publish role with MFA,
so every run prompts for a code, dry runs included: the plan is a read of
the real bucket.

Usage:
    uv run python -m scripts.publish_media --dry-run
    uv run python -m scripts.publish_media
"""

import argparse
import logging
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from pipeline.publish import PublishError, publish_media
from utils.paths import get_dashboard_dir, get_media_dir
from utils.publish_config import load_publish_config
from utils.season_config import known_seasons

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
    """Main entry point for publishing the media drop."""
    parser = argparse.ArgumentParser(
        description="Publish headshots and logos to S3 under the media prefix."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan (upload, skip, delete) and write nothing",
    )
    args = parser.parse_args()

    seasons = known_seasons()
    dashboard_dirs = [get_dashboard_dir(season) for season in seasons]
    media_dir = get_media_dir()
    target = load_publish_config()

    logger.info("=" * 60)
    logger.info(f"Publish media{' (DRY RUN)' if args.dry_run else ''}")
    logger.info(f"  from:    {media_dir}")
    logger.info(f"  seasons: {', '.join(seasons)}")
    logger.info(f"  to:      s3://{target.bucket}/{target.media_prefix}/")
    logger.info(f"  via:     profile {target.profile}")
    logger.info("=" * 60)

    try:
        session = boto3.Session(profile_name=target.profile)
        plan = publish_media(
            media_dir,
            dashboard_dirs,
            target,
            session.client("s3"),
            session.client("cloudfront"),
            dry_run=args.dry_run,
        )
    except PublishError as e:
        logger.error(f"Publish aborted: {e}")
        sys.exit(1)
    except (BotoCoreError, ClientError) as e:
        # A wrong MFA code, an expired session, a missing profile: re-run
        logger.error(f"AWS refused the run: {e}")
        sys.exit(1)

    logger.info("=" * 60)
    if args.dry_run:
        logger.info(
            f"Dry run complete: {len(plan.upload)} would upload, "
            f"{len(plan.skip)} would skip, {len(plan.delete)} would delete"
        )
    else:
        logger.info(
            f"Published media: {len(plan.upload)} uploaded, "
            f"{len(plan.skip)} skipped, {len(plan.delete)} deleted"
        )
        logger.info(f"  {target.base_url}/{target.media_prefix}/")
        logger.info(f"  {len(plan.upload) + len(plan.skip)} public URLs verified")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
