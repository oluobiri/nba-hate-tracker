"""
Centralized data path construction.

All data directory paths should be obtained through this module to ensure
consistent handling of the DATA_DIR environment variable and active season.

Paths are season-scoped: get_raw_dir() returns data/{season}/raw/, where
{season} defaults to the active season in config/season.yaml.

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
)
from utils.season_config import get_active_season


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
    load_dotenv()
    data_root = os.getenv("DATA_DIR", "./data")
    if season is None:
        season = get_active_season()
    return Path(data_root) / season


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


def get_batches_dir() -> Path:
    """
    Get batches directory for Anthropic API requests/responses.

    Returns:
        Path to batches directory (e.g., data/2024-25/batches/).
    """
    return get_data_dir() / BATCHES_DATA_SUBDIR


def get_processed_dir() -> Path:
    """
    Get processed directory for parsed sentiment results.

    Returns:
        Path to processed data directory (e.g., data/2024-25/processed/).
    """
    return get_data_dir() / PROCESSED_DATA_SUBDIR


def get_dashboard_dir() -> Path:
    """
    Get dashboard directory for precomputed aggregates.

    Returns:
        Path to dashboard directory (e.g., data/2024-25/dashboard/).
    """
    return get_data_dir() / DASHBOARD_DATA_SUBDIR
