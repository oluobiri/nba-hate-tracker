"""
Publish target loading from YAML.

This module provides cached access to config/publish.yaml: the bucket,
the data and media key prefixes, CloudFront distribution, public base
URL, and AWS profile the publish steps write through. The file holds no
credentials.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).parent.parent / "config" / "publish.yaml"

REQUIRED_KEYS = (
    "bucket",
    "prefix",
    "media_prefix",
    "distribution_id",
    "base_url",
    "profile",
)


@dataclass(frozen=True)
class PublishTarget:
    """Where the dashboard and media drops land and how the CLI signs in.

    Attributes:
        bucket: S3 bucket behind the distribution's data and media behaviors.
        prefix: Top-level key prefix for the season drops; the public path
            is the S3 key.
        media_prefix: Key prefix for first-party media: <base_url>/<media_prefix>/<name>.
        distribution_id: CloudFront distribution to invalidate.
        base_url: Public origin, scheme included, no trailing slash.
        profile: ~/.aws/config profile that assumes the publish role.
    """

    bucket: str
    prefix: str
    media_prefix: str
    distribution_id: str
    base_url: str
    profile: str


@lru_cache(maxsize=1)
def load_publish_config() -> PublishTarget:
    """
    Load the publish target from config/publish.yaml.

    Deliberately season-independent: one bucket serves every season, so
    this loader does not join the season-cache registry (no override
    guard, no season_override fixture cache-clear).

    Returns:
        The frozen publish target.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If config file is invalid YAML.
        ValueError: If a required key is missing, or base_url ends with
            a slash (keys are joined to it with exactly one).
    """
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}

    missing = [key for key in REQUIRED_KEYS if not config.get(key)]
    if missing:
        raise ValueError(f"{CONFIG_PATH} is missing required keys: {missing}")

    base_url = str(config["base_url"])
    if base_url.endswith("/"):
        raise ValueError(
            f"{CONFIG_PATH}: base_url must not end with a slash, got {base_url!r}"
        )

    return PublishTarget(
        bucket=str(config["bucket"]),
        prefix=str(config["prefix"]).strip("/"),
        media_prefix=str(config["media_prefix"]).strip("/"),
        distribution_id=str(config["distribution_id"]),
        base_url=base_url,
        profile=str(config["profile"]),
    )
