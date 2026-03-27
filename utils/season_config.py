"""
Season configuration loading from YAML.

This module provides cached access to the active season identifier,
date boundaries, and target subreddits from config/season.yaml.

Note: Config is cached per process invocation. If a future script needs
to process multiple seasons in one run, call load_season_config.cache_clear()
before switching.
"""

from functools import lru_cache
from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).parent.parent / "config" / "season.yaml"

REQUIRED_KEYS = {"season", "start_date", "end_date", "subreddits"}


@lru_cache(maxsize=1)
def load_season_config() -> dict:
    """
    Load season configuration from config/season.yaml.

    Returns:
        Dict with keys: season, start_date, end_date, subreddits.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If config file is invalid YAML.
        ValueError: If required keys are missing.
    """
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    missing = REQUIRED_KEYS - set(config)
    if missing:
        raise ValueError(f"season.yaml missing required keys: {missing}")

    return config


def get_active_season() -> str:
    """
    Get the active season identifier from config.

    Returns:
        Season string, e.g. "2024-25".
    """
    return load_season_config()["season"]