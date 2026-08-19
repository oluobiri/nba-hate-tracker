"""
Season configuration loading from YAML.

Two files, two kinds of config:

- config/season.yaml — the *pointers*: `season` (the pipeline's
  operational season) and `published_season` (what the deployed
  dashboard serves). Mutable; moving a pointer never touches a season's
  facts.
- config/<season>/season.yaml — that season's *facts*: the operational
  download window (start_date/end_date), subreddits, the league
  `calendar` block, the `corpus` block, and a lineage `version`.
  Write-once per season.

The active season can be overridden per process via set_season_override()
(the scripts' --season flag), which must be called at script entry before
any season-derived config is loaded — one season per process still holds.
Everything that resolves through get_active_season() follows the override,
including load_season_config()'s facts, so `--season X` reads season X's
window and calendar, not the pointer season's.

The override is process-local module state: spawn-based worker processes
(multiprocessing) would not inherit it and must set it themselves.
"""

import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

import yaml

from utils.config_version import require_version_string


CONFIG_DIR = Path(__file__).parent.parent / "config"
POINTER_PATH = CONFIG_DIR / "season.yaml"

REQUIRED_KEYS = {"season", "start_date", "end_date", "subreddits"}

# The league-calendar key set. Every key must be present in every season's
# file (a value may be null until knowable); the set only grows.
CALENDAR_KEYS = (
    "opening_night",
    "nba_cup_final",
    "christmas",
    "trade_deadline",
    "all_star",
    "play_in_start",
    "playoffs_start",
    "finals_start",
    "finals_end",
)
CORPUS_KEYS = ("raw_comments",)

SEASON_FORMAT = re.compile(r"\d{4}-\d{2}")

_season_override: str | None = None


def _season_facts_path(season: str) -> Path:
    """Resolve the per-season facts file for a season."""
    return CONFIG_DIR / season / "season.yaml"


@lru_cache(maxsize=1)
def load_season_pointer() -> dict:
    """
    Load the season pointers from config/season.yaml.

    Returns:
        Dict with keys: season (str), published_season (str | None).

    Raises:
        FileNotFoundError: If the pointer file doesn't exist.
        yaml.YAMLError: If the file is invalid YAML.
        ValueError: If `season` is missing, or either pointer is not a
            YYYY-YY string.
    """
    with open(POINTER_PATH) as f:
        config = yaml.safe_load(f) or {}

    if "season" not in config:
        raise ValueError(f"season.yaml missing required key 'season': {POINTER_PATH}")

    pointers = {
        "season": config["season"],
        "published_season": config.get("published_season"),
    }
    for key, value in pointers.items():
        if value is None and key == "published_season":
            continue
        if not isinstance(value, str) or not SEASON_FORMAT.fullmatch(value):
            raise ValueError(
                f"season.yaml {key!r} must be a quoted YYYY-YY string, got "
                f"{value!r} in {POINTER_PATH}"
            )
    return pointers


@lru_cache(maxsize=1)
def load_season_config() -> dict:
    """
    Load the active season's facts from config/<season>/season.yaml.

    The season is resolved through get_active_season(), so the --season
    override reaches the facts layer too. Season-derived cache: joins the
    override's warm-cache guard.

    Returns:
        Dict with keys: season, version, start_date, end_date, subreddits
        (tuple), calendar (read-only mapping of the CALENDAR_KEYS to ISO
        date strings or None), corpus (read-only mapping of the
        CORPUS_KEYS to ints or None).

    Raises:
        FileNotFoundError: If the season's facts file doesn't exist.
        yaml.YAMLError: If the file is invalid YAML.
        ValueError: If required keys are missing, the file's `season`
            doesn't match the directory it lives in, `version` isn't a
            quoted string, or a calendar/corpus value is malformed.
    """
    season = get_active_season()
    path = _season_facts_path(season)
    with open(path) as f:
        config = yaml.safe_load(f) or {}

    missing = REQUIRED_KEYS - set(config)
    if missing:
        raise ValueError(f"season.yaml missing required keys: {missing} in {path}")

    if config["season"] != season:
        raise ValueError(
            f"season.yaml 'season' is {config['season']!r} but the file is "
            f"config/{season}/season.yaml"
        )

    if not config["subreddits"]:
        raise ValueError(f"season.yaml 'subreddits' must not be empty: {path}")

    config["version"] = require_version_string(
        config, path, f"season.yaml for season {season!r}"
    )
    config["calendar"] = _validated_block(
        config.get("calendar"), CALENDAR_KEYS, _check_iso_date, "calendar", path
    )
    config["corpus"] = _validated_block(
        config.get("corpus"), CORPUS_KEYS, _check_int, "corpus", path
    )

    # Freeze mutable values so callers can't corrupt the cache
    config["subreddits"] = tuple(config["subreddits"])

    return config


def _validated_block(
    block: dict | None,
    keys: tuple[str, ...],
    check,
    label: str,
    path: Path,
) -> MappingProxyType:
    """
    Validate a write-once fact block: exact key set, typed-or-null values.

    Args:
        block: The parsed YAML mapping (None if absent).
        keys: The required key set, in canonical order.
        check: Validator applied to each non-null value; raises ValueError.
        label: Block name for error messages.
        path: File the block was read from.

    Returns:
        Read-only mapping over the keys in canonical order.

    Raises:
        ValueError: If the block is missing, its key set differs from
            `keys`, or a non-null value fails `check`.
    """
    if not isinstance(block, dict):
        raise ValueError(f"season.yaml missing '{label}' block: {path}")
    if set(block) != set(keys):
        raise ValueError(
            f"season.yaml '{label}' keys must be exactly {sorted(keys)}, "
            f"got {sorted(block)} in {path}"
        )
    for key in keys:
        value = block[key]
        if value is None:
            continue
        try:
            check(value)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"season.yaml {label}.{key} is malformed ({value!r}) in {path}: {e}"
            ) from e
    return MappingProxyType({key: block[key] for key in keys})


def _check_iso_date(value: object) -> None:
    """Require a quoted ISO date string (an unquoted date parses as datetime.date)."""
    if not isinstance(value, str):
        raise TypeError("expected a quoted YYYY-MM-DD string")
    date.fromisoformat(value)


def _check_int(value: object) -> None:
    """Require a plain integer count."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected an integer")


def load_season_config_version() -> str:
    """
    Get the active season's season.yaml version (lineage metadata).

    Returns:
        Version string, e.g. "1.0".
    """
    return load_season_config()["version"]


def get_active_season() -> str:
    """
    Get the active season identifier.

    Returns the process-level override when one is set (see
    set_season_override), otherwise the `season` pointer from
    config/season.yaml.

    Returns:
        Season string, e.g. "2024-25".
    """
    if _season_override is not None:
        return _season_override
    return load_season_pointer()["season"]


def set_season_override(season: str) -> None:
    """
    Override the active season for the rest of this process.

    Call once at script entry (the --season flag), before any
    season-derived config is loaded. Everything that resolves through
    get_active_season() — data paths, the players.yaml loaders, the
    season facts (load_season_config), the aggregates.json season stamp —
    follows the override.

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
            f'Invalid season identifier: {season!r} (expected YYYY-YY, e.g. "2024-25")'
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

    Checks this module's facts loader and the player-config loaders'
    lru_caches; the latter subsume the compiled-pattern cache in
    pipeline/processors.py, which is only ever populated through
    load_player_config().

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
            load_season_config,
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
