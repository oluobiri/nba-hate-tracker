"""
The publish step: a season's dashboard drop to the public bucket.

The upload set is manifest.json plus exactly the files its table registry
names, so nothing else in the dashboard directory ever ships and a season
without a manifest cannot be published. Pre-flight checks every file
against the registry and the contract before a single byte is written.
"""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from pipeline.schemas import SCHEMA_VERSION, Manifest, load_manifest
from utils.constants import MANIFEST_FILENAME

logger = logging.getLogger(__name__)

PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"
MANIFEST_CONTENT_TYPE = "application/json"
PARQUET_CACHE_CONTROL = "public, max-age=86400"
MANIFEST_CACHE_CONTROL = "public, max-age=300"

# Above this boto3's managed transfer goes multipart, and a multipart
# object's ETag is no longer its MD5; every object here is a single PUT.
MULTIPART_THRESHOLD_BYTES = 8 * 1024 * 1024

SCHEMA_VERSION_STAMP_KEY = "schema_version"


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
