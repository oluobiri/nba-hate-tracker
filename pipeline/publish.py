"""
The publish step: a season's dashboard drop to the public bucket.

The upload set is manifest.json plus exactly the files its table registry
names, so nothing else in the dashboard directory ever ships and a season
without a manifest cannot be published. Pre-flight checks every file
against the registry and the contract before a single byte is written.
"""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
import requests
from botocore.exceptions import WaiterError

from pipeline.schemas import SCHEMA_VERSION, Manifest, load_manifest
from utils.constants import MANIFEST_FILENAME
from utils.publish_config import PublishTarget

logger = logging.getLogger(__name__)

PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"
MANIFEST_CONTENT_TYPE = "application/json"
PARQUET_CACHE_CONTROL = "public, max-age=86400"
MANIFEST_CACHE_CONTROL = "public, max-age=300"

# Every object is one put_object call held in memory, so its ETag is its
# MD5; the cap keeps the set small and flags a table that has outgrown
# the contract. It is boto3's own threshold for switching to multipart.
MULTIPART_THRESHOLD_BYTES = 8 * 1024 * 1024

SCHEMA_VERSION_STAMP_KEY = "schema_version"

# S3 caps a single DeleteObjects request at this many keys.
DELETE_BATCH_SIZE = 1000

# CloudFront's own waiter cadence; module constants so tests can zero them.
INVALIDATION_POLL_SECONDS = 20
INVALIDATION_MAX_ATTEMPTS = 30

HTTP_TIMEOUT_SECONDS = 30


class PublishError(Exception):
    """A publish run stopped; nothing after the failing check was written."""


@dataclass(frozen=True)
class LocalObject:
    """One file of the upload set, ready to PUT.

    Attributes:
        key: The S3 key, which is also the public path.
        path: Where the bytes came from.
        body: The exact bytes to upload.
        md5: Hex MD5 of body; equals the object's ETag after a single PUT.
        content_type: Content-Type header for the object.
        cache_control: Cache-Control header for the object.
    """

    key: str
    path: Path
    body: bytes
    md5: str
    content_type: str
    cache_control: str


def season_prefix(prefix: str, season: str) -> str:
    """
    The key prefix a season's files live under.

    Args:
        prefix: The top-level key prefix from publish.yaml.
        season: Season label, e.g. "2025-26".

    Returns:
        Hive-style prefix with a trailing slash, e.g. "data/season=2025-26/".
    """
    return f"{prefix}/season={season}/"


def _check_table(path: Path, expected_rows: int) -> None:
    """Fail unless the parquet exists, matches the registry, and is a single PUT."""
    if not path.exists():
        raise PublishError(f"registered file missing: {path}")

    size = path.stat().st_size
    if size >= MULTIPART_THRESHOLD_BYTES:
        raise PublishError(
            f"{path} is {size} bytes, at or above the single-PUT limit of "
            f"{MULTIPART_THRESHOLD_BYTES} bytes"
        )

    stamped = pl.read_parquet_metadata(path).get(SCHEMA_VERSION_STAMP_KEY)
    if stamped != str(SCHEMA_VERSION):
        raise PublishError(
            f"{path}: {SCHEMA_VERSION_STAMP_KEY} stamp is {stamped!r}, "
            f"contract is {SCHEMA_VERSION}"
        )

    rows = pl.scan_parquet(path).select(pl.len()).collect().item()
    if rows != expected_rows:
        raise PublishError(
            f"{path}: {rows} rows, but the manifest registers {expected_rows} rows"
        )


def _local_object(
    key: str, path: Path, content_type: str, cache_control: str
) -> LocalObject:
    """Read a file once and build its upload record."""
    body = path.read_bytes()
    return LocalObject(
        key=key,
        path=path,
        body=body,
        md5=hashlib.md5(body).hexdigest(),
        content_type=content_type,
        cache_control=cache_control,
    )


def build_upload_set(
    dashboard_dir: Path, season: str, prefix: str
) -> tuple[Manifest, list[LocalObject]]:
    """
    Pre-flight a season's dashboard directory and build its upload set.

    Every check runs before any object is built, so a failure leaves
    nothing half-prepared. The set is the registry's files in registry
    order, then the manifest, so a reader never sees a new manifest
    over old tables.

    Args:
        dashboard_dir: The season's dashboard directory.
        season: The season being published; must match the manifest's.
        prefix: The top-level key prefix from publish.yaml.

    Returns:
        The loaded manifest and the ordered upload set.

    Raises:
        PublishError: If the manifest is missing, names another season
            or contract version, or any registered file is missing,
            mis-stamped, mis-counted, or too large for a single PUT.
    """
    manifest_path = dashboard_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise PublishError(
            f"{manifest_path} not found - a season without a manifest "
            f"cannot be published"
        )
    manifest = load_manifest(manifest_path)

    if manifest["season"] != season:
        raise PublishError(
            f"{manifest_path} is for season {manifest['season']!r}, "
            f"not the requested {season!r}"
        )
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise PublishError(
            f"{manifest_path}: schema_version {manifest['schema_version']}, "
            f"contract is {SCHEMA_VERSION}"
        )

    for entry in manifest["tables"].values():
        _check_table(dashboard_dir / entry["file"], entry["rows"])

    key_prefix = season_prefix(prefix, season)
    objects = [
        _local_object(
            key_prefix + entry["file"],
            dashboard_dir / entry["file"],
            PARQUET_CONTENT_TYPE,
            PARQUET_CACHE_CONTROL,
        )
        for entry in manifest["tables"].values()
    ]
    objects.append(
        _local_object(
            key_prefix + MANIFEST_FILENAME,
            manifest_path,
            MANIFEST_CONTENT_TYPE,
            MANIFEST_CACHE_CONTROL,
        )
    )
    logger.info(f"Pre-flight passed: {len(objects) - 1} tables + manifest for {season}")
    return manifest, objects


@dataclass(frozen=True)
class PublishPlan:
    """What a run will do, decided before any write.

    Attributes:
        upload: Objects to PUT, in order; the manifest is last.
        skip: Objects whose bytes already sit under the key.
        delete: Keys under the season prefix the registry no longer names.
    """

    upload: tuple[LocalObject, ...]
    skip: tuple[LocalObject, ...]
    delete: tuple[str, ...]

    def describe(self) -> str:
        """One block naming every action, for the log and the dry run."""
        lines = [
            f"{len(self.upload)} upload, {len(self.skip)} skip, "
            f"{len(self.delete)} delete"
        ]
        lines += [f"  upload  {o.key}  ({len(o.body)} bytes)" for o in self.upload]
        lines += [f"  skip    {o.key}" for o in self.skip]
        lines += [f"  delete  {key}" for key in self.delete]
        return "\n".join(lines)


def list_remote(s3: Any, bucket: str, key_prefix: str) -> dict[str, str]:
    """
    List what the bucket holds under a season prefix.

    The publish role can list and write but not read objects, so the
    listing's ETags are the only view of remote state; after a single
    PUT they equal the object's MD5.

    Args:
        s3: A boto3 S3 client.
        bucket: The data bucket.
        key_prefix: The season's key prefix, from season_prefix().

    Returns:
        Mapping of key to bare hex ETag for every object under the prefix.
    """
    remote: dict[str, str] = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        for item in page.get("Contents", []):
            remote[item["Key"]] = item["ETag"].strip('"')
    return remote


def build_plan(local: list[LocalObject], remote: dict[str, str]) -> PublishPlan:
    """
    Diff the upload set against the bucket.

    Args:
        local: The ordered upload set from build_upload_set().
        remote: The listing from list_remote() for the same prefix.

    Returns:
        The plan: unchanged objects skip, the rest upload in the given
        order, and remote keys the set does not name are deleted.
    """
    upload = tuple(o for o in local if remote.get(o.key) != o.md5)
    skip = tuple(o for o in local if remote.get(o.key) == o.md5)
    local_keys = {o.key for o in local}
    delete = tuple(sorted(key for key in remote if key not in local_keys))
    return PublishPlan(upload=upload, skip=skip, delete=delete)


def execute_plan(s3: Any, bucket: str, plan: PublishPlan) -> None:
    """
    Write the plan: PUT each upload in order, then delete stale keys.

    Deleting after the last PUT (the manifest) keeps an old manifest's
    tables readable until the new manifest is in place.

    Args:
        s3: A boto3 S3 client.
        bucket: The data bucket.
        plan: The plan from build_plan().

    Raises:
        PublishError: If S3 confirms an ETag other than the local MD5,
            or reports an error for any deleted key.
    """
    for o in plan.upload:
        response = s3.put_object(
            Bucket=bucket,
            Key=o.key,
            Body=o.body,
            ContentType=o.content_type,
            CacheControl=o.cache_control,
        )
        etag = response["ETag"].strip('"')
        if etag != o.md5:
            logger.error(
                f"{o.key} was written but not verified; later uploads and the "
                f"stale-key deletes did not run"
            )
            raise PublishError(
                f"{o.key}: S3 returned ETag {etag!r}, local MD5 is {o.md5!r}"
            )
        logger.info(f"Uploaded {o.key}")

    for start in range(0, len(plan.delete), DELETE_BATCH_SIZE):
        keys = plan.delete[start : start + DELETE_BATCH_SIZE]
        response = s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )
        errors = response.get("Errors", [])
        if errors:
            described = "; ".join(f"{e['Key']}: {e['Code']}" for e in errors)
            raise PublishError(f"delete failed for {len(errors)} keys - {described}")
        for key in keys:
            logger.info(f"Deleted {key}")


def invalidate(cloudfront: Any, distribution_id: str, key_prefix: str) -> str:
    """
    Invalidate everything under the season prefix and wait for completion.

    Args:
        cloudfront: A boto3 CloudFront client.
        distribution_id: The distribution in front of the bucket.
        key_prefix: The season's key prefix, from season_prefix().

    Returns:
        The invalidation ID, for the log.

    Raises:
        PublishError: If the invalidation is not complete within the
            waiter's budget. The objects are already written by then.
    """
    response = cloudfront.create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": [f"/{key_prefix}*"]},
            "CallerReference": datetime.now(timezone.utc).isoformat(),
        },
    )
    invalidation_id = response["Invalidation"]["Id"]
    logger.info(f"Invalidation {invalidation_id} created for /{key_prefix}*")

    waiter = cloudfront.get_waiter("invalidation_completed")
    try:
        waiter.wait(
            DistributionId=distribution_id,
            Id=invalidation_id,
            WaiterConfig={
                "Delay": INVALIDATION_POLL_SECONDS,
                "MaxAttempts": INVALIDATION_MAX_ATTEMPTS,
            },
        )
    except WaiterError as e:
        raise PublishError(
            f"invalidation {invalidation_id} not completed within "
            f"{INVALIDATION_POLL_SECONDS * INVALIDATION_MAX_ATTEMPTS}s; the "
            f"objects are written, the edge is unconfirmed - check it by hand"
        ) from e
    logger.info(f"Invalidation {invalidation_id} completed")
    return invalidation_id


def verify_public_manifest(
    base_url: str,
    key_prefix: str,
    expected_generated_at: str,
    *,
    http_get: Callable[..., Any] = requests.get,
) -> None:
    """
    Assert the public manifest is the one just uploaded.

    The drop is done when the public URL says so: the manifest's
    generated_at is the one field a rebuild changes, so equality means
    the edge serves this build.

    Args:
        base_url: The public origin, no trailing slash.
        key_prefix: The season's key prefix, from season_prefix().
        expected_generated_at: The local manifest's generated_at.
        http_get: requests.get or a stand-in with the same contract.

    Raises:
        PublishError: If the fetch fails or generated_at differs.
    """
    url = f"{base_url}/{key_prefix}{MANIFEST_FILENAME}"
    try:
        response = http_get(url, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        public_generated_at = response.json()["generated_at"]
    except (requests.RequestException, ValueError, KeyError) as e:
        raise PublishError(f"could not read the public manifest at {url}") from e

    if public_generated_at != expected_generated_at:
        raise PublishError(
            f"{url} serves generated_at {public_generated_at!r}, "
            f"expected {expected_generated_at!r}"
        )
    logger.info(f"Public manifest verified: {url} generated_at {public_generated_at}")


def publish_season(
    dashboard_dir: Path,
    season: str,
    target: PublishTarget,
    s3: Any,
    cloudfront: Any,
    *,
    dry_run: bool,
    http_get: Callable[..., Any] = requests.get,
) -> PublishPlan:
    """
    Publish one season's dashboard drop, or plan it.

    Pre-flight, list the bucket, diff; a dry run stops there. Otherwise
    write the plan, invalidate the season path, and confirm the public
    manifest before returning.

    Args:
        dashboard_dir: The season's dashboard directory.
        season: The season being published.
        target: Bucket, prefix, distribution, and base URL.
        s3: A boto3 S3 client assumed as the publish role.
        cloudfront: A boto3 CloudFront client, same role.
        dry_run: Plan only; nothing is written or invalidated.
        http_get: requests.get or a stand-in, for the post-flight.

    Returns:
        The plan that was (or would have been) executed.

    Raises:
        PublishError: From any failed check, write, or verification.
    """
    manifest, objects = build_upload_set(dashboard_dir, season, target.prefix)
    key_prefix = season_prefix(target.prefix, season)
    remote = list_remote(s3, target.bucket, key_prefix)
    plan = build_plan(objects, remote)
    logger.info(f"Plan for s3://{target.bucket}/{key_prefix}\n{plan.describe()}")

    if dry_run:
        logger.info("Dry run - nothing written")
        return plan

    execute_plan(s3, target.bucket, plan)
    invalidate(cloudfront, target.distribution_id, key_prefix)
    verify_public_manifest(
        target.base_url, key_prefix, manifest["generated_at"], http_get=http_get
    )
    return plan
