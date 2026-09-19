"""
First-party media: headshots and logos fetched from the league CDN.

Every tracked player's headshot and every team's logo is downloaded into
the season-independent media directory, and each headshot gets WebP
variants beside its original. Source URLs derive from the ids in
players.yaml and teams.yaml; the config values are cross-checked against
that derivation before anything is fetched.

The CDN refuses automated clients by User-Agent signature, and a refused
request can be an indefinite hang or an HTML page with a 200, so the
User-Agent is a bare product token, the headshot Accept is pinned to
PNG, and every body is sniffed before it is written. Misses are values,
not exceptions: a run is resumable, so partial media is useful and the
script decides the exit code.

Naming, relative to the media root (the publish key is media/ + name):
    headshots/<player_id>.png
    headshots/<player_id>-<width>.webp
    logos/<team_id>.svg

Images are never committed: the repository is public and they belong to
the league.
"""

import logging
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from utils.constants import (
    HEADSHOT_VARIANT_WIDTHS,
    MEDIA_HEADSHOTS_SUBDIR,
    MEDIA_LOGOS_SUBDIR,
    NBA_CDN_HEADSHOT_ACCEPT,
    NBA_CDN_HEADSHOT_URL,
    NBA_CDN_LOGO_URL,
    NBA_CDN_MAX_ATTEMPTS,
    NBA_CDN_REQUEST_DELAY,
    NBA_CDN_RETRY_BACKOFF,
    NBA_CDN_TIMEOUT,
    NBA_CDN_USER_AGENT,
)

logger = logging.getLogger(__name__)

KIND_HEADSHOT = "headshot"
KIND_LOGO = "logo"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Bytes inspected for the SVG root, after the prolog and any comments
SNIFF_WINDOW = 512

# Validated bytes land via a temp file and os.replace, so a killed run
# never leaves a truncated original that resume would trust.
TMP_SUFFIX = ".part"


class MediaError(Exception):
    """A media check failed; nothing after the failing check was written."""


# -----------------------------------------------------------------------------
# Naming and source URLs
# -----------------------------------------------------------------------------


def headshot_source_url(player_id: int) -> str:
    """
    The CDN URL a player's headshot is fetched from.

    Args:
        player_id: NBA player id.

    Returns:
        The 1040x760 PNG URL.
    """
    return NBA_CDN_HEADSHOT_URL.format(player_id=player_id)


def logo_source_url(team_id: int) -> str:
    """
    The CDN URL a team's logo is fetched from.

    Args:
        team_id: NBA team id.

    Returns:
        The primary SVG logo URL.
    """
    return NBA_CDN_LOGO_URL.format(team_id=team_id)


def headshot_name(player_id: int) -> str:
    """
    A headshot original's name, relative to the media root.

    Args:
        player_id: NBA player id.

    Returns:
        e.g. "headshots/203500.png".
    """
    return f"{MEDIA_HEADSHOTS_SUBDIR}/{player_id}.png"


def variant_name(player_id: int, width: int) -> str:
    """
    A headshot variant's name, relative to the media root.

    Args:
        player_id: NBA player id.
        width: Variant width in pixels.

    Returns:
        e.g. "headshots/203500-180.webp".
    """
    return f"{MEDIA_HEADSHOTS_SUBDIR}/{player_id}-{width}.webp"


def logo_name(team_id: int) -> str:
    """
    A logo's name, relative to the media root.

    Args:
        team_id: NBA team id.

    Returns:
        e.g. "logos/1610612737.svg".
    """
    return f"{MEDIA_LOGOS_SUBDIR}/{team_id}.svg"


def verify_config_urls(
    players: dict[str, dict],
    teams: dict[str, dict],
    *,
    headshot_url: Callable[[int], str] = headshot_source_url,
    logo_url: Callable[[int], str] = logo_source_url,
) -> None:
    """
    Assert every config URL equals the form derived from its id.

    The fetch derives URLs from ids, so a hand-edited config value that
    differs would be silently ignored; this makes it loud instead. The
    expected form is pluggable so the same check can guard the
    first-party URLs once the config switches to them.

    Args:
        players: Player name -> metadata with player_id and headshot_url.
        teams: Team name -> config with team_id and logo_url.
        headshot_url: Builds the expected headshot URL from a player id.
        logo_url: Builds the expected logo URL from a team id.

    Raises:
        MediaError: Listing every entry whose URL differs or whose id
            is missing.
    """
    mismatches: list[str] = []
    for name, meta in players.items():
        player_id = meta.get("player_id")
        if player_id is None:
            mismatches.append(f"{name}: no player_id")
            continue
        expected = headshot_url(player_id)
        if meta.get("headshot_url") != expected:
            mismatches.append(
                f"{name}: headshot_url {meta.get('headshot_url')!r}, expected {expected!r}"
            )
    for name, info in teams.items():
        team_id = info.get("team_id")
        if team_id is None:
            mismatches.append(f"{name}: no team_id")
            continue
        expected = logo_url(team_id)
        if info.get("logo_url") != expected:
            mismatches.append(
                f"{name}: logo_url {info.get('logo_url')!r}, expected {expected!r}"
            )
    if mismatches:
        listed = "\n  ".join(mismatches)
        raise MediaError(
            f"{len(mismatches)} config URLs differ from the derived form:\n  {listed}"
        )


# -----------------------------------------------------------------------------
# Byte sniffing
# -----------------------------------------------------------------------------


# What may precede the svg root: an XML prolog, comments, a DOCTYPE
_SVG_PREAMBLE = ((b"<?xml", b"?>"), (b"<!--", b"-->"), (b"<!DOCTYPE", b">"))


def is_png(body: bytes) -> bool:
    """
    Whether the bytes open with the PNG signature.

    Args:
        body: Response bytes.

    Returns:
        True for a PNG.
    """
    return body.startswith(PNG_MAGIC)


def is_svg(body: bytes) -> bool:
    """
    Whether the bytes are an SVG document.

    Skips whitespace, an XML prolog, comments, and a DOCTYPE, then
    requires the svg root element - so a block page's html root fails.

    Args:
        body: Response bytes.

    Returns:
        True for an SVG.
    """
    head = body[:SNIFF_WINDOW].lstrip()
    while True:
        for opener, closer in _SVG_PREAMBLE:
            if head.startswith(opener):
                end = head.find(closer, len(opener))
                if end == -1:
                    return False
                head = head[end + len(closer) :].lstrip()
                break
        else:
            return head.startswith(b"<svg")


_SNIFFERS: dict[str, Callable[[bytes], bool]] = {"PNG": is_png, "SVG": is_svg}


# -----------------------------------------------------------------------------
# The plan
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class MediaAsset:
    """One original to fetch from the CDN.

    Attributes:
        kind: "headshot" or "logo".
        entity_id: The player or team id.
        url: Source URL on the CDN.
        name: Path relative to the media root; the publish key is media/ + name.
        path: Where the original lands locally.
        accept: Accept header to pin, or None for the default.
        format: "PNG" or "SVG"; selects the sniffer and names the miss.
    """

    kind: str
    entity_id: int
    url: str
    name: str
    path: Path
    accept: str | None
    format: str


@dataclass(frozen=True)
class Variant:
    """One WebP variant derived from a headshot original.

    Attributes:
        player_id: The player id.
        width: Target width in pixels.
        source: The original PNG.
        name: Path relative to the media root.
        path: Where the variant lands locally.
    """

    player_id: int
    width: int
    source: Path
    name: str
    path: Path


@dataclass(frozen=True)
class Miss:
    """One asset a run could not produce.

    Attributes:
        name: The asset's name relative to the media root.
        reason: What went wrong, for the report.
    """

    name: str
    reason: str


@dataclass(frozen=True)
class MediaPlan:
    """What a run will do, decided from disk state before any request.

    Attributes:
        fetch: Originals to download.
        present: Originals already on disk.
        generate: Variants to write.
        up_to_date: Variants already on disk.
    """

    fetch: tuple[MediaAsset, ...]
    present: tuple[MediaAsset, ...]
    generate: tuple[Variant, ...]
    up_to_date: tuple[Variant, ...]

    def describe(self) -> str:
        """One block naming every action, for the log and the dry run."""
        lines = [
            f"{len(self.fetch)} fetch, {len(self.present)} present, "
            f"{len(self.generate)} generate, {len(self.up_to_date)} up to date"
        ]
        lines += [f"  fetch     {a.name}" for a in self.fetch]
        lines += [f"  present   {a.name}" for a in self.present]
        lines += [f"  generate  {v.name}" for v in self.generate]
        lines += [f"  up to date  {v.name}" for v in self.up_to_date]
        return "\n".join(lines)


def headshot_asset(player_id: int, media_dir: Path) -> MediaAsset:
    """
    The headshot original for a player.

    Args:
        player_id: NBA player id.
        media_dir: The media root.

    Returns:
        The asset, with the PNG Accept pinned.
    """
    name = headshot_name(player_id)
    return MediaAsset(
        kind=KIND_HEADSHOT,
        entity_id=player_id,
        url=headshot_source_url(player_id),
        name=name,
        path=media_dir / name,
        accept=NBA_CDN_HEADSHOT_ACCEPT,
        format="PNG",
    )


def logo_asset(team_id: int, media_dir: Path) -> MediaAsset:
    """
    The logo for a team.

    Args:
        team_id: NBA team id.
        media_dir: The media root.

    Returns:
        The asset, with no Accept pinned.
    """
    name = logo_name(team_id)
    return MediaAsset(
        kind=KIND_LOGO,
        entity_id=team_id,
        url=logo_source_url(team_id),
        name=name,
        path=media_dir / name,
        accept=None,
        format="SVG",
    )


def build_plan(
    player_ids: Iterable[int],
    team_ids: Iterable[int],
    media_dir: Path,
    *,
    widths: tuple[int, ...] = HEADSHOT_VARIANT_WIDTHS,
    force: bool = False,
) -> MediaPlan:
    """
    Decide what a run will fetch and generate from what is on disk.

    Headshots then logos, each sorted by id. An original fetches unless
    it is present (or force); a variant generates unless it is present
    (or force). A variant is planned against its original's expected
    path whether or not the original exists yet: the executor drops the
    variants of an original that missed.

    Args:
        player_ids: Player ids to cover.
        team_ids: Team ids to cover.
        media_dir: The media root.
        widths: Variant widths to plan per headshot.
        force: Refetch and regenerate everything already on disk.

    Returns:
        The plan.
    """
    assets = [headshot_asset(pid, media_dir) for pid in sorted(player_ids)]
    assets += [logo_asset(tid, media_dir) for tid in sorted(team_ids)]
    variants = [
        Variant(
            player_id=pid,
            width=width,
            source=media_dir / headshot_name(pid),
            name=variant_name(pid, width),
            path=media_dir / variant_name(pid, width),
        )
        for pid in sorted(player_ids)
        for width in widths
    ]

    def present(path: Path) -> bool:
        return not force and path.exists()

    return MediaPlan(
        fetch=tuple(a for a in assets if not present(a.path)),
        present=tuple(a for a in assets if present(a.path)),
        generate=tuple(v for v in variants if not present(v.path)),
        up_to_date=tuple(v for v in variants if present(v.path)),
    )


# -----------------------------------------------------------------------------
# Phase one: originals
# -----------------------------------------------------------------------------


def _write_atomic(path: Path, body: bytes) -> None:
    """Write bytes to a temp file beside the target, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + TMP_SUFFIX)
    tmp.write_bytes(body)
    os.replace(tmp, path)


def fetch_asset(
    asset: MediaAsset,
    *,
    http_get: Callable[..., Any] = requests.get,
    timeout: int = NBA_CDN_TIMEOUT,
    max_attempts: int = NBA_CDN_MAX_ATTEMPTS,
    retry_backoff: float = NBA_CDN_RETRY_BACKOFF,
) -> None:
    """
    Download one original, validate its bytes, and write it atomically.

    Connection errors and timeouts are retried with exponential backoff;
    an HTTP error status is a real answer and propagates at once.

    Args:
        asset: The original to fetch.
        http_get: requests.get or a stand-in with the same contract.
        timeout: Per-request timeout in seconds.
        max_attempts: Total attempts (1 initial + retries).
        retry_backoff: Base seconds for the backoff between retries.

    Raises:
        requests.HTTPError: On a non-2xx status.
        requests.ConnectionError | requests.Timeout: The last transient
            error, after max_attempts is exhausted.
        MediaError: If the body is not the expected image format.
    """
    headers = {"User-Agent": NBA_CDN_USER_AGENT}
    if asset.accept is not None:
        headers["Accept"] = asset.accept

    last_error: requests.RequestException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = http_get(asset.url, headers=headers, timeout=timeout)
            break
        except (requests.ConnectionError, requests.Timeout) as e:
            last_error = e
            if attempt < max_attempts:
                wait = retry_backoff * (2 ** (attempt - 1))
                logger.warning(
                    f"Transient CDN error on {asset.name} "
                    f"(attempt {attempt}/{max_attempts}), retrying in {wait:.0f}s: {e}"
                )
                time.sleep(wait)
    else:
        raise last_error  # type: ignore[misc]  # loop always sets it before exiting

    response.raise_for_status()
    body = response.content
    if not _SNIFFERS[asset.format](body):
        raise MediaError(f"{asset.name}: not a {asset.format} (got {body[:16]!r})")
    _write_atomic(asset.path, body)


def fetch_originals(
    assets: Iterable[MediaAsset],
    *,
    delay: float = NBA_CDN_REQUEST_DELAY,
    http_get: Callable[..., Any] = requests.get,
    timeout: int = NBA_CDN_TIMEOUT,
    max_attempts: int = NBA_CDN_MAX_ATTEMPTS,
    retry_backoff: float = NBA_CDN_RETRY_BACKOFF,
) -> list[Miss]:
    """
    Fetch every planned original, collecting misses instead of stopping.

    Args:
        assets: The plan's fetch set, in order.
        delay: Seconds to wait after each request, misses included.
        http_get: requests.get or a stand-in with the same contract.
        timeout: Per-request timeout in seconds.
        max_attempts: Total attempts per asset.
        retry_backoff: Base seconds for the backoff between retries.

    Returns:
        One Miss per asset that could not be fetched or validated.
    """
    misses: list[Miss] = []
    for asset in assets:
        try:
            fetch_asset(
                asset,
                http_get=http_get,
                timeout=timeout,
                max_attempts=max_attempts,
                retry_backoff=retry_backoff,
            )
            logger.info(f"Fetched {asset.name}")
        except (requests.RequestException, MediaError) as e:
            reason = f"{type(e).__name__}: {e}"
            logger.warning(f"Missed {asset.name} - {reason}")
            misses.append(Miss(name=asset.name, reason=reason))
        time.sleep(delay)
    return misses
