"""
Config-lineage registry: which config version stamps which produced file.

A config-derived file carries the version of each config it was derived
under in its parquet metadata, so drift between the file and the live
config is detectable when it is read. This module is the one place the
stamp keys are spelled and the one place an output's configs are
declared: the write sites, the read-side drift checks and the
manifest's config_versions block all resolve through it.
"""

import logging
from collections.abc import Callable, Mapping
from pathlib import Path

from utils.player_config import load_player_config_version
from utils.season_config import load_season_config_version
from utils.team_config import load_team_config_version

# Config name -> its version loader. The manifest publishes every entry.
CONFIG_VERSION_LOADERS: dict[str, Callable[[], str]] = {
    "players": load_player_config_version,
    "teams": load_team_config_version,
    "season": load_season_config_version,
}

# Produced file -> the configs its rows derive from. Every file the
# pipeline writes is registered, an empty tuple meaning config-free; an
# unregistered name is a KeyError at the write site, never a silently
# unstamped file. The verdict sidecar is the exception: it carries the
# pool's stamp forward rather than the live version (collect_results).
OUTPUT_CONFIGS: dict[str, tuple[str, ...]] = {
    "sentiment": ("players", "teams"),
    "target_pool": ("players",),
    "posts_bridge": ("teams",),
    "player_overall": (),
    "player_temporal": (),
    "player_fan_team": (),
    "fan_team_overall": (),
    "game_sentiment": (),
    "players": ("players",),
    "teams": ("teams",),
    "games": (),
    "player_games": (),
    "posts": (),
    "comment_samples": (),
}


def config_stamp_key(config: str) -> str:
    """
    The parquet metadata key a config's version is stamped under.

    Args:
        config: A registered config name ("players", "teams", "season").

    Returns:
        The key, e.g. "players_config_version".

    Raises:
        KeyError: If the config has no registered version loader.
    """
    if config not in CONFIG_VERSION_LOADERS:
        raise KeyError(
            f"{config!r} is not a registered config "
            f"(known: {sorted(CONFIG_VERSION_LOADERS)})"
        )
    return f"{config}_config_version"


def config_versions() -> dict[str, str]:
    """
    Read every registered config's live version.

    Returns:
        Config name -> version string, in registry order.
    """
    return {name: load() for name, load in CONFIG_VERSION_LOADERS.items()}


def config_stamps(output: str) -> dict[str, str]:
    """
    The live config-version stamps a produced file must carry.

    Args:
        output: A registered produced-file name (a DASHBOARD_OUTPUT_SCHEMAS
            key, or "sentiment" for the fact).

    Returns:
        Stamp key -> live version for each config the output derives
        from; empty for a config-free output.

    Raises:
        KeyError: If the output is not registered in OUTPUT_CONFIGS.
    """
    if output not in OUTPUT_CONFIGS:
        raise KeyError(
            f"{output!r} is not registered in OUTPUT_CONFIGS - every produced "
            f"file declares the configs it derives from so it is never written "
            f"unstamped"
        )
    return {
        config_stamp_key(config): CONFIG_VERSION_LOADERS[config]()
        for config in OUTPUT_CONFIGS[output]
    }


def check_config_stamps(
    path: Path,
    metadata: Mapping[str, str],
    output: str,
    *,
    subject: str,
    remedy: str,
    log: logging.Logger,
) -> None:
    """
    Warn when a produced file's config stamps are missing or drifted.

    The read-side counterpart of config_stamps(): for each config the
    output is registered under, compare the file's stamp with the live
    version. A stale file is legitimate to read, just not silently.
    Absence is reported distinctly from drift.

    Args:
        path: The file the metadata was read from, for the messages.
        metadata: The file's parquet metadata.
        output: A registered produced-file name (OUTPUT_CONFIGS key).
        subject: What the file is, for the messages ("pool", "bridge").
        remedy: What drift means for the reader and what to do about it.
        log: The calling module's logger, so warnings carry its name.

    Raises:
        KeyError: If the output is not registered in OUTPUT_CONFIGS.
    """
    for config in OUTPUT_CONFIGS[output]:
        key = config_stamp_key(config)
        stamped = metadata.get(key)
        active = CONFIG_VERSION_LOADERS[config]()
        if stamped is None:
            log.warning(
                f"{path} carries no {key} stamp - {subject} lineage cannot be verified"
            )
        elif stamped != active:
            log.warning(
                f"{path}: {key} drift - {subject} built under config {stamped!r} "
                f"but active config is {active!r}; {remedy}"
            )
