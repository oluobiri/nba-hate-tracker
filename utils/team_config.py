"""
Team configuration loading from YAML.

This module provides cached access to team names, abbreviations, and aliases
from config/teams.yaml for flair normalization.
"""

from functools import lru_cache
from pathlib import Path

import yaml

from utils.config_version import require_version_string


CONFIG_PATH = Path(__file__).parent.parent / "config" / "teams.yaml"


@lru_cache(maxsize=1)
def load_team_config() -> dict[str, dict]:
    """
    Load teams from config/teams.yaml.

    Returns:
        Dict mapping team name to team info (abbreviation, aliases).

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If config file is invalid YAML.
    """
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    return config.get("teams", {})


@lru_cache(maxsize=1)
def load_team_config_version() -> str:
    """
    Load the config version string from config/teams.yaml.

    The version is lineage metadata: it is stamped into teams.parquet at
    the aggregation write site, giving fan_team derivations the same
    config-lineage treatment as players.yaml's version stamp on
    sentiment.parquet.

    Deliberately season-independent: teams.yaml is not season-scoped, so
    this loader does not join the season-cache registry (no override
    guard, no season_override fixture cache-clear) — by design, not
    omission.

    Returns:
        Version string, e.g. "2.1".

    Raises:
        FileNotFoundError: If config file doesn't exist.
        yaml.YAMLError: If config file is invalid YAML.
        ValueError: If the config has no 'version' key, or the value is
            not a quoted string (an unquoted version parses as a YAML
            float and would silently mis-stamp, e.g. 2.10 -> "2.1").
    """
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    return require_version_string(config, CONFIG_PATH, "teams.yaml")


@lru_cache(maxsize=1)
def build_alias_to_team_map() -> dict[str, str]:
    """
    Invert team aliases to map each alias to its canonical team name.

    Returns:
        Dict mapping lowercase alias to canonical team name.
        Includes team names, abbreviations, and all aliases as keys.
    """
    teams = load_team_config()
    alias_map: dict[str, str] = {}
    for team_name, info in teams.items():
        alias_map[team_name.lower()] = team_name
        alias_map[info["abbreviation"].lower()] = team_name
        for alias in info.get("aliases", []):
            alias_map[alias.lower()] = team_name
    return alias_map
