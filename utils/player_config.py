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

    players = config.get("players", {})
    short_aliases = frozenset(
        alias.lower() for alias in config.get("short_aliases", [])
    )

    return players, short_aliases
