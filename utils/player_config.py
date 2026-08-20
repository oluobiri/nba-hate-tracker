"""
Player configuration loading from YAML.

This module provides cached access to player aliases, short alias lists,
player metadata, and the config version string from
config/{season}/players.yaml.

Note: Config is cached per process invocation via @lru_cache. One season
per process — the season is resolved through get_active_season() at first
load, honoring a set_season_override() made at script entry (the --season
flag). The override's guard raises if these caches are already warm, so
set it before anything triggers a load.
"""

from functools import lru_cache
from pathlib import Path

import yaml

from utils.config_version import require_version_string
from utils.season_config import get_active_season


def _get_players_path() -> Path:
    """Resolve the players.yaml path for the active season."""
    season = get_active_season()
    return Path(__file__).parent.parent / "config" / season / "players.yaml"


@lru_cache(maxsize=1)
def load_player_config() -> tuple[dict[str, list[str]], frozenset[str]]:
    """
    Load players and short_aliases from config/{season}/players.yaml.

    Returns:
        Tuple of (players dict, short_aliases frozenset).
        - players: Dict mapping player name to list of aliases.
        - short_aliases: Frozenset of aliases requiring word boundary matching.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If config file is invalid YAML.
    """
    with open(_get_players_path()) as f:
        config = yaml.safe_load(f)

    raw_players = config.get("players", {})

    # Unwrap enriched structure: extract aliases from each player dict
    players: dict[str, list[str]] = {}
    for player_name, player_data in raw_players.items():
        if isinstance(player_data, dict):
            players[player_name] = player_data.get("aliases", [])
        else:
            players[player_name] = player_data

    short_aliases = frozenset(
        alias.lower() for alias in config.get("short_aliases", [])
    )

    return players, short_aliases


@lru_cache(maxsize=1)
def build_alias_to_player_map() -> dict[str, str]:
    """
    Invert player aliases to map each alias to its canonical player name.

    Returns:
        Dict mapping lowercase alias to canonical player name.
        Includes canonical names themselves as keys.
    """
    players, _ = load_player_config()
    alias_map: dict[str, str] = {}
    for player_name, aliases in players.items():
        alias_map[player_name.lower()] = player_name
        for alias in aliases:
            alias_map[alias.lower()] = player_name
    return alias_map


def _normalize_player_name(name: str) -> str:
    """
    Normalize a player name for alias-map lookup.

    Lowercases, strips periods, and collapses whitespace so classifier output
    variants (trailing "Jr." or initials like "O.G.") match the period-free
    aliases and canonical names in the config.

    Args:
        name: Raw player name, typically a classifier sentiment_player value.

    Returns:
        Normalized lookup key.
    """
    return " ".join(name.lower().replace(".", "").split())


def resolve_sentiment_player(name: str | None, alias_map: dict[str, str]) -> str | None:
    """
    Resolve a classifier sentiment_player value to a canonical player name.

    Normalizes punctuation and case before the alias-map lookup, so model
    output variants (e.g. "Michael Porter Jr." with a trailing period) resolve
    to the tracked canonical name rather than being dropped. Returns None when
    the name maps to no tracked player — the signal coverage analysis uses to
    surface discussed-but-untracked players.

    Args:
        name: The classifier's free-text sentiment_player value (may be None).
        alias_map: Mapping of lowercase aliases to canonical player names, as
            returned by build_alias_to_player_map().

    Returns:
        Canonical player name, or None if the name does not resolve.
    """
    if not name:
        return None
    return alias_map.get(_normalize_player_name(name))


@lru_cache(maxsize=1)
def load_player_config_version() -> str:
    """
    Load the config version string from config/{season}/players.yaml.

    The version (MAJOR = roster add/drop, MINOR = alias-only change) is
    lineage metadata: it is stamped into sentiment.parquet at assembly
    and checked against the on-disk config at aggregation read time.

    Returns:
        Version string, e.g. "4.2".

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If config file is invalid YAML.
        ValueError: If the config has no 'version' key, or the value is
            not a quoted string (an unquoted version parses as a YAML
            float and would silently mis-stamp, e.g. 4.10 -> "4.1").
    """
    path = _get_players_path()
    with open(path) as f:
        config = yaml.safe_load(f)

    return require_version_string(
        config, path, f"players.yaml for season {get_active_season()!r}"
    )


@lru_cache(maxsize=1)
def load_player_metadata() -> dict[str, dict]:
    """
    Load player metadata from config/{season}/players.yaml.

    Returns:
        Dict mapping player name to metadata dict containing:
        - team: Team name (str)
        - conference: Conference name (str, "East" or "West")
        - player_id: NBA player ID (int)
        - headshot_url: CDN URL for player headshot (str)

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If config file is invalid YAML.
    """
    with open(_get_players_path()) as f:
        config = yaml.safe_load(f)

    raw_players = config.get("players", {})
    metadata: dict[str, dict] = {}

    for player_name, player_data in raw_players.items():
        if isinstance(player_data, dict):
            metadata[player_name] = {
                "team": player_data.get("team"),
                "conference": player_data.get("conference"),
                "player_id": player_data.get("player_id"),
                "headshot_url": player_data.get("headshot_url"),
            }

    return metadata
