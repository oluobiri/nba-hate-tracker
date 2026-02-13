"""
Player configuration loading from YAML.

This module provides cached access to player aliases and short alias lists
from config/players.yaml for player mention detection.
"""

from functools import lru_cache
from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).parent.parent / "config" / "players.yaml"


@lru_cache(maxsize=1)
def load_player_config() -> tuple[dict[str, list[str]], frozenset[str]]:
    """
    Load players and short_aliases from config/players.yaml.

    Returns:
        Tuple of (players dict, short_aliases frozenset).
        - players: Dict mapping player name to list of aliases.
        - short_aliases: Frozenset of aliases requiring word boundary matching.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If config file is invalid YAML.
    """
    with open(CONFIG_PATH) as f:
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


@lru_cache(maxsize=1)
def load_player_metadata() -> dict[str, dict]:
    """
    Load player metadata from config/players.yaml.

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
    with open(CONFIG_PATH) as f:
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
