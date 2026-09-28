"""
Recap curation loading from YAML.

config/{season}/recaps.yaml lists the games replayed as recaps: one
(game_id, slug) per entry, in page order. Every season carries the file,
empty when nothing is curated, so the lineage registry stays uniform:
the file's quoted version stamps each recap it produces, and the loader
mirrors utils/player_config.py (one season per process, resolved through
get_active_season() at first load, cached with lru_cache).

Shape is validated here; existence is not. Whether a game is in the
Game dimension, a slug in the Player dimension, the game threaded and
its play-by-play on disk are frame questions, answered where the frames
are (pipeline/recaps.py).
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from utils.config_version import require_version_string
from utils.season_config import get_active_season

RECAPS_FILENAME = "recaps.yaml"
_GAME_ID = re.compile(r"\d{10}")
_ENTRY_KEYS = frozenset({"game_id", "slug"})


@dataclass(frozen=True)
class RecapSpec:
    """One curated recap: a game and the player it follows."""

    game_id: str
    slug: str


def _get_recaps_path() -> Path:
    """Resolve the recaps.yaml path for the active season."""
    season = get_active_season()
    return Path(__file__).parent.parent / "config" / season / RECAPS_FILENAME


def _read(path: Path) -> dict:
    """Parse the file as a mapping; an empty document is an empty mapping."""
    with open(path) as f:
        config = yaml.safe_load(f)
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError(f"recaps.yaml must be a mapping: {path}")
    return config


@lru_cache(maxsize=1)
def load_recaps_config() -> tuple[RecapSpec, ...]:
    """
    Load the curated recaps from config/{season}/recaps.yaml, in page order.

    Returns:
        The entries as RecapSpec, in file order; empty when the file
        curates nothing.

    Raises:
        FileNotFoundError: If the season has no recaps.yaml.
        yaml.YAMLError: If the file is invalid YAML.
        ValueError: If the file's season is not its directory's, 'recaps'
            is not a list, an entry has keys other than game_id and slug,
            a game_id is not a quoted 10-digit id (unquoted, YAML reads a
            leading zero as octal), a slug is empty, or an entry repeats.
    """
    path = _get_recaps_path()
    season = get_active_season()
    config = _read(path)

    if config.get("season") != season:
        raise ValueError(
            f"recaps.yaml 'season' is {config.get('season')!r} but the file is "
            f"config/{season}/{RECAPS_FILENAME}"
        )

    entries = config.get("recaps")
    if not isinstance(entries, list):
        raise ValueError(
            f"recaps.yaml 'recaps' must be a list, empty when nothing is "
            f"curated: {path}"
        )

    specs: list[RecapSpec] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
            raise ValueError(
                f"recaps.yaml entry {index} must have exactly game_id and slug: {path}"
            )
        game_id, slug = entry["game_id"], entry["slug"]
        if not isinstance(game_id, str) or not _GAME_ID.fullmatch(game_id):
            raise ValueError(
                f"recaps.yaml entry {index}: game_id must be a quoted 10-digit "
                f"id, got {game_id!r}: {path}"
            )
        if not isinstance(slug, str) or not slug:
            raise ValueError(
                f"recaps.yaml entry {index}: slug must be a non-empty string, "
                f"got {slug!r}: {path}"
            )
        spec = RecapSpec(game_id, slug)
        if spec in specs:
            raise ValueError(
                f"recaps.yaml entry {index} repeats {game_id} / {slug}: {path}"
            )
        specs.append(spec)

    return tuple(specs)


@lru_cache(maxsize=1)
def load_recaps_config_version() -> str:
    """
    Load the version string from config/{season}/recaps.yaml.

    The version (MAJOR = entry add/drop, MINOR = reorder) is lineage
    metadata: it is stamped into every recap file and published in the
    manifest's config_versions.

    Returns:
        Version string, e.g. "1.0".

    Raises:
        FileNotFoundError: If the season has no recaps.yaml.
        yaml.YAMLError: If the file is invalid YAML.
        ValueError: If the file has no 'version' key, or the value is not
            a quoted string.
    """
    path = _get_recaps_path()
    return require_version_string(
        _read(path), path, f"recaps.yaml for season {get_active_season()!r}"
    )
