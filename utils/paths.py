"""
Centralized data path construction.

All data directory paths should be obtained through this module to ensure
consistent handling of the DATA_DIR environment variable and active season.

Paths are season-scoped: get_raw_dir() returns data/{season}/raw/, where
{season} defaults to the active season in config/season.yaml. The one
exception is get_media_dir(): media assets serve every season, so they
sit beside the season directories.

Functions (not module-level constants) ensure environment is read at runtime,
not import time.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from utils.constants import (
    RAW_DATA_SUBDIR,
    FILTERED_DATA_SUBDIR,
    BATCHES_DATA_SUBDIR,
    PROCESSED_DATA_SUBDIR,
    DASHBOARD_DATA_SUBDIR,
    REFERENCE_DATA_SUBDIR,
    MEDIA_DATA_SUBDIR,
)
from utils.season_config import get_active_season


def _data_root() -> Path:
    """
    The data root: DATA_DIR from the environment (with .env support).

    Returns:
        Path to the data root (default: ./data).
    """
    load_dotenv()
    return Path(os.getenv("DATA_DIR", "./data"))


def get_data_dir(season: str | None = None) -> Path:
    """
    Get the season-scoped data directory.

    Reads DATA_DIR from environment (with .env support), then appends
    the season subdirectory. Default: ./data/{active_season}

    Args:
        season: Season identifier (e.g., "2024-25"). Defaults to active
            season from config/season.yaml.

    Returns:
        Path to season data directory (e.g., data/2024-25/).
    """
    if season is None:
        season = get_active_season()
    return _data_root() / season


def get_raw_dir() -> Path:
    """
    Get the raw data directory.

    Returns:
        Path to raw data directory (e.g., data/2024-25/raw/).
    """
    return get_data_dir() / RAW_DATA_SUBDIR


def get_filtered_dir() -> Path:
    """
    Get the filtered data directory.

    Returns:
        Path to filtered data directory (e.g., data/2024-25/filtered/).
    """
    return get_data_dir() / FILTERED_DATA_SUBDIR


def get_batches_dir(stage: str = "sentiment") -> Path:
    """
    Get a classifier stage's batches directory (requests, responses, state).

    Args:
        stage: Classifier stage name; each stage runs in its own directory.

    Returns:
        Path to the stage's batches directory
        (e.g., data/2024-25/batches/sentiment/).
    """
    return get_data_dir() / BATCHES_DATA_SUBDIR / stage


def get_processed_dir() -> Path:
    """
    Get processed directory for parsed sentiment results.

    Returns:
        Path to processed data directory (e.g., data/2024-25/processed/).
    """
    return get_data_dir() / PROCESSED_DATA_SUBDIR


def get_dashboard_dir(season: str | None = None) -> Path:
    """
    Get dashboard directory for precomputed aggregates.

    Args:
        season: Season identifier (e.g., "2024-25"). Defaults to the
            active season; the media publish passes every known season.

    Returns:
        Path to dashboard directory (e.g., data/2024-25/dashboard/).
    """
    return get_data_dir(season) / DASHBOARD_DATA_SUBDIR


def get_reference_dir() -> Path:
    """
    Get reference directory for cached external snapshots (e.g. rosters).

    Returns:
        Path to reference directory (e.g., data/2024-25/reference/).
    """
    return get_data_dir() / REFERENCE_DATA_SUBDIR


def get_media_dir() -> Path:
    """
    Get the media directory for headshot and logo assets.

    Season-independent: one set of originals and variants serves every
    season, so the directory sits beside the season directories.

    Returns:
        Path to the media directory (e.g., data/media/).
    """
    return _data_root() / MEDIA_DATA_SUBDIR
