"""
Method-example curation loading from YAML.

config/{season}/method_examples.yaml lists the comments the How it works
page shows: one (slot, comment_id) per entry, in page order. Every season
carries the file, empty when nothing is curated, so the lineage registry
stays uniform: the file's quoted version stamps the table it produces,
and the loader mirrors utils/recaps_config.py (one season per process,
resolved through get_active_season() at first load, cached with
lru_cache).

Shape is validated here; fit is not. Whether a comment is in the fact
and satisfies its slot's requirements is a frame question, answered
where the frames are (pipeline/method_examples.py).
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from utils.config_version import require_version_string
from utils.season_config import get_active_season

METHOD_EXAMPLES_FILENAME = "method_examples.yaml"
SLOTS = ("trace", "case", "read", "slip", "quote_check")
_ENTRY_KEYS = frozenset({"slot", "comment_id"})


@dataclass(frozen=True)
class MethodExampleSpec:
    """One curated example: the slot it fills and the comment that fills it."""

    slot: str
    comment_id: str


def _get_method_examples_path() -> Path:
    """Resolve the method_examples.yaml path for the active season."""
    season = get_active_season()
    return Path(__file__).parent.parent / "config" / season / METHOD_EXAMPLES_FILENAME


def _read(path: Path) -> dict:
    """Parse the file as a mapping; an empty document is an empty mapping."""
    with open(path) as f:
        config = yaml.safe_load(f)
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError(f"method_examples.yaml must be a mapping: {path}")
    return config


@lru_cache(maxsize=1)
def load_method_examples_config() -> tuple[MethodExampleSpec, ...]:
    """
    Load the curated examples from config/{season}/method_examples.yaml, in page order.

    Returns:
        The entries as MethodExampleSpec, in file order; empty when the
        file curates nothing.

    Raises:
        FileNotFoundError: If the season has no method_examples.yaml.
        yaml.YAMLError: If the file is invalid YAML.
        ValueError: If the file's season is not its directory's,
            'examples' is not a list, an entry has keys other than slot
            and comment_id, a slot is not one of SLOTS, a comment_id is
            not a non-empty string, or a comment_id repeats.
    """
    path = _get_method_examples_path()
    season = get_active_season()
    config = _read(path)

    if config.get("season") != season:
        raise ValueError(
            f"method_examples.yaml 'season' is {config.get('season')!r} but the "
            f"file is config/{season}/{METHOD_EXAMPLES_FILENAME}"
        )

    entries = config.get("examples")
    if not isinstance(entries, list):
        raise ValueError(
            f"method_examples.yaml 'examples' must be a list, empty when nothing "
            f"is curated: {path}"
        )

    specs: list[MethodExampleSpec] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
            raise ValueError(
                f"method_examples.yaml entry {index} must have exactly slot and "
                f"comment_id: {path}"
            )
        slot, comment_id = entry["slot"], entry["comment_id"]
        if slot not in SLOTS:
            raise ValueError(
                f"method_examples.yaml entry {index}: slot must be one of "
                f"{', '.join(SLOTS)}, got {slot!r}: {path}"
            )
        if not isinstance(comment_id, str) or not comment_id:
            raise ValueError(
                f"method_examples.yaml entry {index}: comment_id must be a "
                f"non-empty string, got {comment_id!r}: {path}"
            )
        if comment_id in seen:
            raise ValueError(
                f"method_examples.yaml entry {index} repeats {comment_id}: {path}"
            )
        seen.add(comment_id)
        specs.append(MethodExampleSpec(slot, comment_id))

    return tuple(specs)


@lru_cache(maxsize=1)
def load_method_examples_config_version() -> str:
    """
    Load the version string from config/{season}/method_examples.yaml.

    The version (MAJOR = entry add/drop, MINOR = reorder) is lineage
    metadata: it is stamped into method_examples.parquet and published
    in the manifest's config_versions.

    Returns:
        Version string, e.g. "1.0".

    Raises:
        FileNotFoundError: If the season has no method_examples.yaml.
        yaml.YAMLError: If the file is invalid YAML.
        ValueError: If the file has no 'version' key, or the value is not
            a quoted string.
    """
    path = _get_method_examples_path()
    return require_version_string(
        _read(path), path, f"method_examples.yaml for season {get_active_season()!r}"
    )
