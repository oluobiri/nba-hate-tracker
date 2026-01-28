"""
Centralized data path construction.

All data directory paths should be obtained through this module to ensure
consistent handling of the DATA_DIR environment variable.

Functions (not module-level constants) ensure environment is read at runtime,
not import time.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from utils.constants import FILTERED_DATA_SUBDIR, RAW_DATA_SUBDIR


def get_data_dir() -> Path:
    """
    Get the data directory from environment or use default.

    Reads DATA_DIR from environment (with .env support).
    Default: ./data

    Returns:
        Path to data directory.
    """
    load_dotenv()
    data_dir = os.getenv("DATA_DIR", "./data")
    return Path(data_dir)


def get_raw_dir() -> Path:
    """
    Get the raw data directory.

    Returns:
        Path to raw data directory (e.g., data/raw/).
    """
    return get_data_dir() / RAW_DATA_SUBDIR


def get_filtered_dir() -> Path:
    """
    Get the filtered data directory.

    Returns:
        Path to filtered data directory (e.g., data/filtered/).
    """
    return get_data_dir() / FILTERED_DATA_SUBDIR
