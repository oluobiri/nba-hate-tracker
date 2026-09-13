"""
The Post bridge: posts_bridge.parquet and posts.parquet.

Derives post_type and game_id for every r/NBA post from its flair and
title under the active config: title spellings resolve to canonical
Team names through teams.yaml, and the title's team pair plus the
Eastern-time day of created_utc resolve to a game through the Game
dimension. The raw posts file holds every post; this module decides
what ships.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from pipeline.nba_stats import check_snapshot_season
from pipeline.schemas import POSTS_SCHEMA, validate_schema

logger = logging.getLogger(__name__)

RAW_POSTS_FILENAME = "r_nba_posts.jsonl"
POSTS_BRIDGE_FILENAME = "posts_bridge.parquet"

# Source field -> bridge column; `name` is the t3_ fullname the fact's
# link_id carries, `id` is the bare id.
RAW_POST_FIELDS = {
    "name": "post_id",
    "title": "title",
    "created_utc": "created_utc",
    "score": "score",
    "num_comments": "num_comments",
    "link_flair_text": "link_flair_text",
}
RAW_POSTS_SCHEMA = pl.Schema(
    {col: POSTS_SCHEMA[col] for col in RAW_POST_FIELDS.values()}
)
UNLINKED_TITLES_LOGGED = 10

GAME_THREAD = "game_thread"
POST_GAME_THREAD = "post_game_thread"
OTHER = "other"
POST_TYPES = (GAME_THREAD, POST_GAME_THREAD, OTHER)
FLAIR_POST_TYPES = {"Game Thread": GAME_THREAD, "Post Game Thread": POST_GAME_THREAD}

# Threads follow the US schedule, so a post's calendar day is Eastern.
# A game thread is posted on the game's day; a post-game thread on the
# same day or, after a late West-coast tip, the next; the mods' titles
# sometimes carry the UTC day, one off either way.
POST_LOCAL_TZ = ZoneInfo("America/New_York")
GAME_DATE_WINDOW_DAYS = (-1, 0, 1)

# Title fallback for flair-stripped (mod-removed) threads. Anchored, so
# the daily "... + Game Thread Index" posts never match.
_TITLE_POST_TYPES = (
    (re.compile(r"^\[?\s*game thread\b", re.IGNORECASE), GAME_THREAD),
    (re.compile(r"^\[?\s*post[- ]?game thread\b", re.IGNORECASE), POST_GAME_THREAD),
)
# "(October 04, 2025)" on the mods' threads, "| Apr 28, 2026" on the bots'.
_TITLE_DATE = re.compile(r"\b([A-Z][a-z]{2,8} \d{1,2}, \d{4})\b")
_TITLE_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y")
# A (W-L) record looks like a score; strip records before reading one.
_RECORD = re.compile(r"\(\d+-\d+\)")
_SCORE = re.compile(r"(?<!\d)(\d{2,3})\s*[-–]\s*(\d{2,3})(?!\d)")


def classify_post(title: str, flair: str | None) -> str:
    """
    Derive post_type from the post's flair, falling back to its title.

    The two thread flairs decide outright, and any other flair is
    `other` whatever the title says (the daily index post carries
    "Game Thread" mid-title). Only a post with no flair at all — the
    mods strip it when they remove a duplicate — is classified by an
    anchored title prefix.

    Args:
        title: Post title.
        flair: link_flair_text, None when unflaired.

    Returns:
        One of POST_TYPES.
    """
    if flair is not None:
        return FLAIR_POST_TYPES.get(flair, OTHER)
    for pattern, post_type in _TITLE_POST_TYPES:
        if pattern.match(title):
            return post_type
    return OTHER


def build_title_name_map(team_config: dict[str, dict]) -> dict[str, str]:
    """
    Map the spellings a title may use for a team to its canonical name.

    Canonical names plus the multi-word entries of teams.yaml aliases[]
    (the flair fragments), lowercased. Single-token aliases are left
    out: `was` and `tor` sit inside ordinary words of a post-game
    title, and an abbreviation never appears in one.

    Args:
        team_config: Team config dict from load_team_config().

    Returns:
        Lowercased spelling -> canonical team name.
    """
    name_map = {team.lower(): team for team in team_config}
    for team, info in team_config.items():
        for alias in info.get("aliases", []):
            if " " in alias:
                name_map[alias.lower()] = team
    return name_map


def extract_team_pair(title: str, name_map: dict[str, str]) -> frozenset[str] | None:
    """
    Find the two teams a thread title names, as an unordered pair.

    Spellings are matched longest-first on word boundaries and consumed
    as they match, so "Portland Trail Blazers" is never also read as
    "Trail Blazers". The pair is unordered because the three game-thread
    title formats disagree on which side is listed first.

    Args:
        title: Post title.
        name_map: Spelling -> canonical name, from build_title_name_map().

    Returns:
        The two canonical names, or None when the title names fewer
        than two distinct teams (non-games, non-NBA opponents).
    """
    remaining = title.lower()
    found: list[tuple[int, str]] = []
    for spelling in sorted(name_map, key=len, reverse=True):
        pattern = rf"(?<![a-z0-9]){re.escape(spelling)}(?![a-z0-9])"
        for match in re.finditer(pattern, remaining):
            found.append((match.start(), name_map[spelling]))
        remaining = re.sub(pattern, lambda m: " " * len(m.group()), remaining)
    # Title order, so a third team named later ("to face the Spurs")
    # never displaces the matchup.
    teams: list[str] = []
    for _, team in sorted(found):
        if team not in teams:
            teams.append(team)
    if len(teams) < 2:
        return None
    return frozenset(teams[:2])


def parse_title_date(title: str) -> date | None:
    """
    Read a "Month DD, YYYY" date out of a thread title, if it carries one.

    Args:
        title: Post title.

    Returns:
        The date, or None when the title has no such date.
    """
    match = _TITLE_DATE.search(title)
    if match is None:
        return None
    for fmt in _TITLE_DATE_FORMATS:
        try:
            return datetime.strptime(match.group(1), fmt).date()
        except ValueError:
            continue
    return None


def parse_score(title: str) -> set[int] | None:
    """
    Read the final score out of a post-game title, as an unordered set.

    Args:
        title: Post title.

    Returns:
        The two scores, or None when the title carries none.
    """
    match = _SCORE.search(_RECORD.sub("", title))
    if match is None:
        return None
    return {int(match.group(1)), int(match.group(2))}


def local_date(created_utc: int) -> date:
    """
    The Eastern calendar day of a UTC epoch timestamp.

    Args:
        created_utc: Epoch seconds.

    Returns:
        The date in POST_LOCAL_TZ.
    """
    return (
        datetime.fromtimestamp(created_utc, tz=timezone.utc)
        .astimezone(POST_LOCAL_TZ)
        .date()
    )


def build_game_index(
    games: pl.DataFrame,
) -> dict[tuple[frozenset[str], date], list[dict]]:
    """
    Index the Game dimension by (unordered team pair, game date).

    Args:
        games: Frame conforming to GAMES_SCHEMA.

    Returns:
        (pair, game_date) -> the game rows on that day (one, barring a
        doubleheader), each with game_id, game_date and both scores.
    """
    index: dict[tuple[frozenset[str], date], list[dict]] = {}
    for row in games.select(
        "game_id", "game_date", "home_team", "away_team", "home_score", "away_score"
    ).iter_rows(named=True):
        key = (frozenset({row["home_team"], row["away_team"]}), row["game_date"])
        index.setdefault(key, []).append(row)
    return index


def match_game(
    pair: frozenset[str],
    created_utc: int,
    title_date: date | None,
    score: set[int] | None,
    index: dict[tuple[frozenset[str], date], list[dict]],
) -> str | None:
    """
    Resolve a thread to the game it is about.

    Candidates are the pair's games within a day either side of the
    thread's Eastern creation day. More than one (a back-to-back) is
    narrowed by the title date, then the score, then the creation day
    itself; a tie that survives all three is left unlinked and logged.

    Args:
        pair: The two teams the title names.
        created_utc: The post's creation time, epoch seconds.
        title_date: A date read from the title, or None.
        score: The score read from the title, or None.
        index: From build_game_index().

    Returns:
        The game_id, or None when no game or no single game fits.
    """
    created_day = local_date(created_utc)
    candidates = [
        game
        for days in GAME_DATE_WINDOW_DAYS
        for game in index.get((pair, created_day + timedelta(days=days)), [])
    ]
    for narrow in (
        lambda g: title_date is not None and g["game_date"] == title_date,
        lambda g: score is not None and {g["home_score"], g["away_score"]} == score,
        lambda g: g["game_date"] == created_day,
    ):
        if len(candidates) < 2:
            break
        candidates = [g for g in candidates if narrow(g)] or candidates
    if len(candidates) == 1:
        return candidates[0]["game_id"]
    if candidates:
        logger.warning(
            f"Ambiguous game for {sorted(pair)} around {created_day}: "
            f"{[g['game_id'] for g in candidates]}; left unlinked"
        )
    return None


def read_raw_posts(path: Path) -> pl.DataFrame:
    """
    Stream the raw posts download, keeping the bridge's source fields.

    A post carries a hundred-odd fields; the six the bridge needs are
    projected line by line so the file never sits in memory whole.

    Args:
        path: The r_<subreddit>_posts.jsonl download.

    Returns:
        Frame conforming to RAW_POSTS_SCHEMA, in file order.
    """
    rows = []
    with open(path) as f:
        for line in f:
            post = json.loads(line)
            rows.append(
                {col: post.get(field) for field, col in RAW_POST_FIELDS.items()}
            )
    posts = pl.DataFrame(rows, schema=RAW_POSTS_SCHEMA)
    logger.info(f"Read {posts.height} posts from {path}")
    return posts


def build_posts_bridge(
    posts: pl.DataFrame, games: pl.DataFrame, team_config: dict[str, dict]
) -> pl.DataFrame:
    """
    Derive post_type, game_id and is_primary for every post.

    Only game and post-game threads are resolved to a game. Split,
    second-half and repost threads share a game_id; is_primary marks the
    largest by num_comments per (game_id, post_type), and is false on
    every unlinked row. Coverage is logged: threads linked, games with
    a thread, and why the rest did not link.

    Args:
        posts: Frame conforming to RAW_POSTS_SCHEMA.
        games: Frame conforming to GAMES_SCHEMA.
        team_config: Team config dict from load_team_config().

    Returns:
        Frame conforming to POSTS_SCHEMA, sorted by creation time then id.

    Raises:
        ValueError: If a post_id appears more than once.
    """
    duplicated = posts.group_by("post_id").len().filter(pl.col("len") > 1)
    if duplicated.height:
        raise ValueError(
            "posts grain is one row per post; duplicated: "
            f"{duplicated.sort('post_id').head(10)['post_id'].to_list()}"
        )

    name_map = build_title_name_map(team_config)
    index = build_game_index(games)
    post_types: list[str] = []
    game_ids: list[str | None] = []
    unparsed: list[str] = []
    unmatched: list[str] = []
    for title, flair, created_utc in posts.select(
        "title", "link_flair_text", "created_utc"
    ).iter_rows():
        title = title or ""
        post_type = classify_post(title, flair)
        game_id = None
        if post_type != OTHER:
            pair = extract_team_pair(title, name_map)
            if pair is None:
                unparsed.append(title)
            else:
                game_id = match_game(
                    pair,
                    created_utc,
                    parse_title_date(title),
                    parse_score(title),
                    index,
                )
                if game_id is None:
                    unmatched.append(title)
        post_types.append(post_type)
        game_ids.append(game_id)

    # Rank within (game, type) by size so the largest thread is primary;
    # over() follows frame order, hence the sort first.
    bridge = (
        posts.with_columns(
            pl.Series("post_type", post_types, dtype=pl.String),
            pl.Series("game_id", game_ids, dtype=pl.String),
        )
        .sort(["num_comments", "post_id"], descending=[True, False])
        .with_columns(
            (
                pl.col("game_id").is_not_null()
                & (pl.int_range(pl.len()).over(["game_id", "post_type"]) == 0)
            ).alias("is_primary")
        )
        .select(POSTS_SCHEMA.names())
        .cast(dict(POSTS_SCHEMA))
        .sort(["created_utc", "post_id"])
    )

    for post_type in (GAME_THREAD, POST_GAME_THREAD):
        threads = bridge.filter(pl.col("post_type") == post_type)
        linked = threads.filter(pl.col("game_id").is_not_null())
        logger.info(
            f"{post_type}: {linked.height}/{threads.height} linked to a game; "
            f"{linked['game_id'].n_unique()}/{games.height} games have one"
        )
    logger.info(
        f"Unlinked threads: {len(unparsed)} name fewer than two teams, "
        f"{len(unmatched)} name a pair with no game within a day"
    )
    for label, titles in (("no team pair", unparsed), ("no game", unmatched)):
        if titles:
            logger.info(f"  {label} (head): {titles[:UNLINKED_TITLES_LOGGED]}")
    logger.info(
        f"posts bridge: {bridge.height} posts, "
        f"{bridge.filter(pl.col('post_type') == OTHER).height} other"
    )
    return bridge


def load_posts_table(
    reference_dir: Path,
    games: pl.DataFrame,
    games_fetched_at: str | None,
    comment_samples: pl.DataFrame,
) -> tuple[pl.DataFrame, dict]:
    """
    Select the published posts from the season's bridge.

    The published table is the game and post-game threads plus every
    post a receipt points at (its title is the receipt's context). A
    missing bridge degrades to an empty table with a warning, so
    aggregation stays runnable before scripts.process_posts has run.
    The bridge's season stamp is checked, and a bridge derived from a
    different game-log fetch than the game tables is flagged; a
    game_id the dimension no longer carries fails the build outright.

    Args:
        reference_dir: Season reference directory holding the bridge.
        games: Frame conforming to GAMES_SCHEMA, this run's dimension.
        games_fetched_at: The game tables' snapshot fetch date, or None.
        comment_samples: Frame conforming to COMMENT_SAMPLES_SCHEMA.

    Returns:
        (posts, metadata) where metadata carries post_count and
        posts_processed_at (the bridge's stamp, or None when absent).

    Raises:
        ValueError: If the bridge links a post to a game_id absent from
            games, or does not conform to POSTS_SCHEMA.
    """
    path = reference_dir / POSTS_BRIDGE_FILENAME
    if not path.exists():
        logger.warning(
            f"{path} not found (run scripts.process_posts) - posts will be empty"
        )
        return pl.DataFrame(schema=POSTS_SCHEMA), {
            "post_count": 0,
            "posts_processed_at": None,
        }

    stamps = check_snapshot_season(path, subject="post bridge", log=logger)
    if stamps.get("games_fetched_at") != games_fetched_at:
        logger.warning(
            f"{path} was derived from a game-log fetch of "
            f"{stamps.get('games_fetched_at')!r} but the game tables come from "
            f"{games_fetched_at!r}; re-run scripts.process_posts"
        )
    bridge = pl.read_parquet(path)
    validate_schema(bridge, POSTS_SCHEMA, str(path))
    unknown = bridge.filter(
        pl.col("game_id").is_not_null()
        & ~pl.col("game_id").is_in(games["game_id"].to_list())
    )
    if unknown.height:
        raise ValueError(
            f"{path} links {unknown.height} post(s) to game_id(s) absent from games: "
            f"{unknown['game_id'].unique().sort().head(10).to_list()}; re-run "
            "scripts.process_posts against the current snapshot"
        )

    is_thread = pl.col("post_type") != OTHER
    is_receipt_context = pl.col("post_id").is_in(
        comment_samples["link_id"].unique().to_list()
    )
    posts = bridge.filter(is_thread | is_receipt_context)
    thread_count = bridge.filter(is_thread).height
    logger.info(
        f"posts: {posts.height} published of {bridge.height} "
        f"({thread_count} threads, {posts.height - thread_count} receipt context)"
    )
    return posts, {
        "post_count": posts.height,
        "posts_processed_at": stamps.get("processed_at"),
    }
