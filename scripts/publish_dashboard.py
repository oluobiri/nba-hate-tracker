"""
Publish a season's dashboard drop to the public bucket.

Pre-flights the season's dashboard directory against its manifest, diffs
the upload set against the bucket, writes what changed (tables first,
manifest last), deletes keys the registry no longer names, invalidates
the season path, and confirms the public manifest. A dry run stops
after the diff and prints the plan.

The AWS profile in config/publish.yaml assumes the publish role with
MFA, so every run prompts for a code, dry runs included: the plan is a
read of the real bucket.

Usage:
    uv run python -m scripts.publish_dashboard --season 2025-26 --dry-run
    uv run python -m scripts.publish_dashboard --season 2025-26
"""

import argparse
import logging
import sys

import boto3

from pipeline.publish import PublishError, publish_season
from utils.paths import get_dashboard_dir
from utils.publish_config import load_publish_config
from utils.season_config import set_season_override

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
    """Main entry point for publishing a season's dashboard drop."""
    parser = argparse.ArgumentParser(
        description="Publish a season's dashboard parquets and manifest to S3."
    )
    parser.add_argument(
        "--season",
        required=True,
        metavar="YYYY-YY",
        help='The season to publish (e.g. "2025-26"); must match its manifest',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan (upload, skip, delete) and write nothing",
    )
    args = parser.parse_args()

    # The season override must land before any season-scoped path resolves
    set_season_override(args.season)
    dashboard_dir = get_dashboard_dir()
    target = load_publish_config()

    logger.info("=" * 60)
    logger.info(f"Publish {args.season}{' (DRY RUN)' if args.dry_run else ''}")
    logger.info(f"  from: {dashboard_dir}")
    logger.info(f"  to:   s3://{target.bucket}/{target.prefix}/season={args.season}/")
    logger.info(f"  via:  profile {target.profile}")
    logger.info("=" * 60)

    session = boto3.Session(profile_name=target.profile)
    s3 = session.client("s3")
    cloudfront = session.client("cloudfront")

    try:
        plan = publish_season(
            dashboard_dir,
            args.season,
            target,
            s3,
            cloudfront,
            dry_run=args.dry_run,
        )
    except PublishError as e:
        logger.error(f"Publish aborted: {e}")
        sys.exit(1)

    logger.info("=" * 60)
    if args.dry_run:
        logger.info(
            f"Dry run complete: {len(plan.upload)} would upload, "
            f"{len(plan.skip)} would skip, {len(plan.delete)} would delete"
        )
    else:
        logger.info(
            f"Published {args.season}: {len(plan.upload)} uploaded, "
            f"{len(plan.skip)} skipped, {len(plan.delete)} deleted"
        )
        logger.info(f"  {target.base_url}/{target.prefix}/season={args.season}/")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
