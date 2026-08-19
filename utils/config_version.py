"""
Shared validation for the lineage `version` key in YAML configs.

players.yaml, teams.yaml, and season.yaml each carry a quoted
MAJOR.MINOR `version` that gets stamped into produced files; every
loader validates it through require_version_string() so the rule (must
exist, must be a string) has one home.
"""

from pathlib import Path


def require_version_string(config: dict | None, path: Path, label: str) -> str:
    """
    Return a config's `version` value, requiring a quoted string.

    Args:
        config: Parsed YAML document (None when the file is empty).
        path: Path the config was read from, for the error message.
        label: Human name of the config file, e.g. "players.yaml".

    Returns:
        The version string, e.g. "4.2".

    Raises:
        ValueError: If there is no 'version' key, or the value is not a
            string (an unquoted version parses as a YAML float and would
            silently mis-stamp lineage, e.g. 4.10 -> "4.1").
    """
    version = (config or {}).get("version")
    if version is None:
        raise ValueError(f"{label} has no 'version' key: {path}")
    if not isinstance(version, str):
        raise ValueError(
            f"{label} version must be a quoted string, got "
            f"{version!r} ({type(version).__name__}) in {path}"
        )
    return version
