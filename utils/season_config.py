"""
Season configuration loading from YAML.

This module provides cached access to the active season identifier,
date boundaries, and target subreddits from config/season.yaml.

The active season can be overridden per process via set_season_override()
(the scripts' --season flag), which must be called at script entry before
any season-derived config is loaded — one season per process still holds.
The override redirects only the season identifier (paths, players.yaml);
load_season_config()'s other fields (start_date, end_date, subreddits)
deliberately keep their on-disk values, so scripts that consume those
(download_comments) must not use the override.

The override is process-local module state: spawn-based worker processes
(multiprocessing) would not inherit it and must set it themselves.
"""

import re
from functools import lru_cache
from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).parent.parent / "config" / "season.yaml"

REQUIRED_KEYS = {"season", "start_date", "end_date", "subreddits"}

SEASON_FORMAT = re.compile(r"\d{4}-\d{2}")

_season_override: str | None = None


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

    if not config["subreddits"]:
        raise ValueError("season.yaml 'subreddits' must not be empty")

    # Freeze mutable values so callers can't corrupt the cache
    config["subreddits"] = tuple(config["subreddits"])

    return config


def get_active_season() -> str:
    """
    Get the active season identifier.

    Returns the process-level override when one is set (see
    set_season_override), otherwise the value from config/season.yaml.

    Returns:
        Season string, e.g. "2024-25".
    """
    if _season_override is not None:
        return _season_override
    return load_season_config()["season"]


def set_season_override(season: str) -> None:
    """
    Override the active season for the rest of this process.

    Call once at script entry (the --season flag), before any
    season-derived config is loaded. Everything that resolves through
    get_active_season() — data paths, the players.yaml loaders, the
    aggregates.json season stamp — follows the override; the remaining
    load_season_config() fields (start_date, end_date, subreddits) keep
    their on-disk values.

    Args:
        season: Season identifier, e.g. "2024-25".

    Raises:
        ValueError: If season is not in YYYY-YY format.
        RuntimeError: If season-derived caches are already warm — data
            was already loaded for another season, and clearing it
            silently could mask work that acted on the wrong season.
    """
    if not SEASON_FORMAT.fullmatch(season):
        raise ValueError(
            f"Invalid season identifier: {season!r} (expected YYYY-YY, "
            'e.g. "2024-25")'
        )
    _ensure_season_caches_cold()
    global _season_override
    _season_override = season


def clear_season_override() -> None:
    """Clear the season override, restoring config/season.yaml resolution."""
    global _season_override
    _season_override = None


def _ensure_season_caches_cold() -> None:
    """
    Fail fast if season-derived caches were populated before the override.

    Checks the player-config loaders' lru_caches; these subsume the
    compiled-pattern cache in pipeline/processors.py, which is only ever
    populated through load_player_config().

    Raises:
        RuntimeError: Naming the warm caches, if any.
    """
    from utils.player_config import (
        build_alias_to_player_map,
        load_player_config,
        load_player_config_version,
        load_player_metadata,
    )

    warm = [
        fn.__name__
        for fn in (
            load_player_config,
            build_alias_to_player_map,
            load_player_metadata,
            load_player_config_version,
        )
        if fn.cache_info().currsize > 0
    ]
    if warm:
        raise RuntimeError(
            f"set_season_override() called after season-derived caches were "
            f"populated: {warm}. Set the override at script entry, before "
            "any config loading."
        )
