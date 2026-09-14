"""Human-readable formatting utilities: durations, file sizes, URL slugs."""

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def format_duration(seconds: float) -> str:
    """
    Format seconds as human-readable duration.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like "45.2s", "2m 5s", or "1h 2m 5s".
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours}h {minutes}m {secs}s"


def format_size(size_bytes: int) -> str:
    """
    Format bytes as human-readable string.

    Args:
        size_bytes: Size in bytes.

    Returns:
        Formatted string like "1.5 KB", "2.3 MB", or "1.0 GB".
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def slugify(name: str) -> str:
    """
    Fold a display name to a URL slug.

    NFKD-decompose and drop the combining marks (Jokić -> Jokic),
    lowercase, collapse every run of non-alphanumerics to one hyphen,
    trim the ends: "De'Aaron Fox" -> "de-aaron-fox", "P.J. Washington"
    -> "p-j-washington".

    Args:
        name: Display name, e.g. a players.yaml key.

    Returns:
        The slug; empty only if the name had no alphanumerics.
    """
    folded = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", name)
        if not unicodedata.combining(ch)
    )
    return _NON_ALNUM.sub("-", folded.lower()).strip("-")
