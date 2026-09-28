"""
Recaps: a game's live thread replayed against its play-by-play.

A recap places one game's plays and one player's comments on a shared
clock. The archive's period markers carry Eastern wall-clock time to the
minute ("Start of 1st Period (8:17 PM EST)"), so the game clock maps to
wall-clock time by a straight line inside each period, and a comment's
wall-clock timestamp maps back to game seconds through the same line.
Comments posted during a break pin to the break; comments before tip-off
and after the buzzer keep their phase. The mapping is a derivation with
an error, measured (never corrected) once per season by the room's
reactions to tracked players' blocks, steals and dunks.

Every function here is a frame transform; the archive and the fact are
read at the edges by the aggregation stage.
"""

import json
import logging
import os
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from pipeline.nba_stats import play_by_play_path
from pipeline.posts import GAME_THREAD, POST_LOCAL_TZ
from pipeline.schemas import (
    RECAP_COMMENTS_SCHEMA,
    RECAP_FRAME_SCHEMAS,
    RECAP_NULLABLE_COLUMNS,
    RECAP_PERIODS_SCHEMA,
    RECAP_PLAYS_SCHEMA,
    RECAP_POPULATION,
    RECAP_STINTS_SCHEMA,
    RECAP_THREADS_SCHEMA,
    SCHEMA_VERSION,
    AlignmentFigures,
    ClassifierIdentity,
    PeriodCounts,
    RecapEntry,
    RecapHeader,
    recap_file,
    validate_nullability,
    validate_schema,
)
from utils.constants import (
    RECAPS_SUBDIR,
    RECAP_ANCHOR_MIN_REACTIONS,
    RECAP_ANCHOR_VOCABULARY,
    RECAP_ANCHOR_WINDOW_SECONDS,
    RECAP_ROOM_BODIES_PER_BUCKET,
    RECAP_ROOM_BUCKET_SECONDS,
)
from utils.recaps_config import RecapSpec

logger = logging.getLogger(__name__)

# --- The game clock ----------------------------------------------------------

PERIOD_SECONDS = 720
OVERTIME_SECONDS = 300
REGULATION_PERIODS = 4
PERIOD_ACTION_TYPE = "period"
PERIOD_START = "start"
PERIOD_END = "end"
PHASE_PRE, PHASE_LIVE, PHASE_BREAK, PHASE_POST = "pre", "live", "break", "post"

# The marker's wall clock, e.g. "(8:17 PM EST)". The label reads EST all
# year at every venue, so it is Eastern local time, parsed in GAME_TZ.
_WALL_CLOCK = r"\((?P<hour>\d{1,2}):(?P<minute>\d{2}) (?P<meridiem>AM|PM) E[SD]T\)"
# The archive's clock, e.g. "PT11M21.00S": time remaining in the period.
_CLOCK = r"^PT(?P<minutes>\d+)M(?P<seconds>\d+(?:\.\d+)?)S$"
GAME_TZ = POST_LOCAL_TZ
_ROLLOVER_MINUTES = 12 * 60  # a drop this large in a marker's clock is midnight

PERIOD_COLUMNS = [
    "period",
    "start_seconds",
    "end_seconds",
    "start_wall",
    "end_wall",
    "start_action_id",
    "end_action_id",
]


# --- The plays --------------------------------------------------------------

SHOT_ACTION_TYPES = ("Made Shot", "Missed Shot")
SUBSTITUTION_ACTION_TYPE = "Substitution"
# The archive's action_type is blank on every block and steal; the kind
# is read from the description instead.
_BLANK_TYPE_KINDS = (("BLOCK", "block"), ("STEAL", "steal"))
ACTION_TYPE_KINDS = {
    "Made Shot": "shot",
    "Missed Shot": "shot",
    "Free Throw": "free_throw",
    "Rebound": "rebound",
    "Turnover": "turnover",
    "Foul": "foul",
    "Timeout": "timeout",
    "Jump Ball": "jump_ball",
    "Violation": "violation",
    "Ejection": "ejection",
}
KIND_PERIOD_START, KIND_PERIOD_END = "period_start", "period_end"
KIND_SUB_IN, KIND_SUB_OUT, KIND_OTHER = "sub_in", "sub_out", "other"
SUB_KINDS = (KIND_SUB_IN, KIND_SUB_OUT)
# Every kind the slice keeps regardless of who acted
_SLICE_KINDS = (KIND_PERIOD_START, KIND_PERIOD_END, "timeout")
# Running totals the focus player's own descriptions carry, e.g.
# "(2 PTS)", "(Off:1 Def:3)", "(1 BLK)", "(P1.T2)" on a foul or turnover.
_TOTAL_PATTERNS = {
    "pts": r"\((\d+) PTS\)",
    "blk": r"\((\d+) BLK\)",
    "stl": r"\((\d+) STL\)",
}
_OFFENSIVE_REBOUNDS = r"\(Off:(\d+) Def:\d+\)"
_DEFENSIVE_REBOUNDS = r"\(Off:\d+ Def:(\d+)\)"
_PERSONAL_COUNT = r"\(P(\d+)[.)]"
TOTAL_COLUMNS = ["pts", "reb", "ast", "blk", "stl", "tov", "pf"]


# --- Comments, anchors, the document ---------------------------------------

SENTIMENTS = ("neg", "pos", "neu")
# A reaction anchor: a tracked player's block, steal or made dunk that
# comments about him name, by RECAP_ANCHOR_VOCABULARY, within a minute
MADE_SHOT_ACTION_TYPE = "Made Shot"
DUNK_SUB_TYPE = "Dunk"
KIND_DUNK = "dunk"
ANCHOR_CANDIDATE_SCHEMA = pl.Schema(
    {
        "game_id": pl.String,
        "action_id": pl.Int64,
        "kind": pl.String,
        "attributed_player": pl.String,
        "game_seconds": pl.Int64,
        "wall_clock": pl.Int64,
        "third": pl.Int64,  # 1..3: which third of its period the play fell in
    }
)
SCAN_MIN_LIVE_N = 500
_TMP_SUFFIX = ".part"
# A recap reads the fact's sentiment, never the target verifier
CLASSIFIER_STAGES = ("sentiment",)


class RecapError(ValueError):
    """A recap could not be built; the message names the game and the cause."""


def period_length() -> pl.Expr:
    """Seconds in the `period` column's period: regulation or overtime."""
    return (
        pl.when(pl.col("period") <= REGULATION_PERIODS)
        .then(PERIOD_SECONDS)
        .otherwise(OVERTIME_SECONDS)
        .cast(pl.Int64)
    )


def parse_clock_seconds(clock: pl.Expr) -> pl.Expr:
    """
    Seconds remaining in the period from the archive's clock string.

    Args:
        clock: An expression over clock strings ("PT11M21.00S").

    Returns:
        A Float64 expression, null where the string does not parse.
    """
    parts = clock.str.extract_groups(_CLOCK)
    return parts.struct.field("minutes").cast(pl.Float64) * 60 + parts.struct.field(
        "seconds"
    ).cast(pl.Float64)


def build_periods(pbp: pl.DataFrame, game_dates: pl.DataFrame) -> pl.DataFrame:
    """
    The game clock of one or more games from their period markers.

    Each period's start and end marker gives its wall-clock bounds; game
    seconds accumulate across periods (720 each in regulation, 300 in
    overtime). A marker's time is combined with the game's date in
    GAME_TZ, rolling to the next day once the clock passes midnight.

    Args:
        pbp: Play-by-play rows (PLAY_BY_PLAY_SCHEMA), one or more games.
        game_dates: ``game_id`` and ``game_date`` (Date) for every game.

    Returns:
        One row per (game_id, period): ``game_id`` then PERIOD_COLUMNS,
        sorted by game and period.

    Raises:
        RecapError: If a game has no date, a marker does not carry a
            wall clock, a period lacks a start or an end, a marker
            repeats, periods are not 1..N, a period ends before it
            starts, or a period starts before the previous one ended.
    """
    markers = (
        pbp.filter(pl.col("action_type") == PERIOD_ACTION_TYPE)
        .select("game_id", "period", "sub_type", "description", "action_id")
        .join(game_dates.select("game_id", "game_date"), on="game_id", how="left")
        .sort("game_id", "action_id")
    )
    undated = markers.filter(pl.col("game_date").is_null())
    if undated.height:
        raise RecapError(
            f"no game date for {sorted(undated['game_id'].unique().to_list())}"
        )

    parts = markers.with_columns(
        pl.col("description").str.extract_groups(_WALL_CLOCK).alias("wall")
    ).unnest("wall")
    unparsed = parts.filter(pl.col("hour").is_null())
    if unparsed.height:
        first = unparsed.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: period marker without a wall clock at "
            f"action {first['action_id']}: {first['description']!r}"
        )

    hour24 = (pl.col("hour").cast(pl.Int64) % 12) + pl.when(
        pl.col("meridiem") == "PM"
    ).then(12).otherwise(0)
    minute_of_day = hour24 * 60 + pl.col("minute").cast(pl.Int64)
    parts = parts.with_columns(minute_of_day.alias("minute_of_day")).with_columns(
        # A clock reading half a day earlier than it did is the game
        # crossing midnight; a smaller drop is a defective marker
        (
            pl.col("minute_of_day")
            < pl.col("minute_of_day").cum_max().over("game_id") - _ROLLOVER_MINUTES
        )
        .cast(pl.Int64)
        .cum_max()
        .over("game_id")
        .alias("day_offset")
    )
    day = pl.col("game_date") + pl.duration(days=pl.col("day_offset"))
    local = pl.datetime(
        day.dt.year(),
        day.dt.month(),
        day.dt.day(),
        pl.col("minute_of_day") // 60,
        pl.col("minute_of_day") % 60,
    )
    parts = parts.with_columns(
        # The hour that repeats when daylight time ends is 1-2 AM Eastern;
        # a marker there takes the first instance, and a wrong guess fails
        # the ordering checks below rather than shipping
        local.dt.replace_time_zone(str(GAME_TZ), ambiguous="earliest")
        .dt.epoch("s")
        .alias("wall")
    )

    repeated = (
        parts.group_by("game_id", "period", "sub_type").len().filter(pl.col("len") > 1)
    )
    if repeated.height:
        first = repeated.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: period {first['period']} has "
            f"{first['len']} {first['sub_type']} markers"
        )

    def side(sub_type: str, prefix: str) -> pl.DataFrame:
        return parts.filter(pl.col("sub_type") == sub_type).select(
            "game_id",
            "period",
            pl.col("wall").alias(f"{prefix}_wall"),
            pl.col("action_id").alias(f"{prefix}_action_id"),
        )

    periods = (
        side(PERIOD_START, "start")
        .join(
            side(PERIOD_END, "end"), on=["game_id", "period"], how="full", coalesce=True
        )
        .sort("game_id", "period")
    )
    incomplete = periods.filter(
        pl.col("start_wall").is_null() | pl.col("end_wall").is_null()
    )
    if incomplete.height:
        first = incomplete.row(0, named=True)
        missing = PERIOD_START if first["start_wall"] is None else PERIOD_END
        raise RecapError(
            f"{first['game_id']}: period {first['period']} has no {missing} marker"
        )

    periods = periods.with_columns(
        (pl.int_range(pl.len()).over("game_id") + 1).alias("expected_period"),
        pl.col("start_wall").shift(-1).over("game_id").alias("next_start_wall"),
    )
    gap = periods.filter(pl.col("period") != pl.col("expected_period"))
    if gap.height:
        first = gap.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: periods are not contiguous from 1 "
            f"(found {first['period']} where {first['expected_period']} was expected)"
        )
    inverted = periods.filter(pl.col("end_wall") <= pl.col("start_wall"))
    if inverted.height:
        first = inverted.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: period {first['period']} ends at or before it starts"
        )
    overlap = periods.filter(pl.col("next_start_wall") < pl.col("end_wall"))
    if overlap.height:
        first = overlap.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: period {first['period'] + 1} starts before "
            f"period {first['period']} ends"
        )

    return (
        periods.with_columns(period_length().alias("length"))
        .with_columns(
            (pl.col("length").cum_sum().over("game_id") - pl.col("length")).alias(
                "start_seconds"
            )
        )
        .with_columns((pl.col("start_seconds") + pl.col("length")).alias("end_seconds"))
        .select("game_id", *PERIOD_COLUMNS)
    )


def align_comments(comments: pl.DataFrame, periods: pl.DataFrame) -> pl.DataFrame:
    """
    Place comments on the game clock of their game.

    A comment posted inside a period maps by a straight line between the
    period's markers; one posted in a break pins to the end of the period
    just played; before tip-off it is ``pre`` at second 0, after the last
    buzzer ``post`` at the game's last second.

    Args:
        comments: Rows with ``game_id`` and ``created_utc``; any other
            columns ride along.
        periods: The game clock from build_periods, ``game_id`` included.

    Returns:
        The comments with ``game_seconds``, ``phase`` and ``period``
        (null outside live and break) added, in the input's row order.
        A comment whose game has no clock in ``periods`` reads as
        ``pre``; callers pass the games they aligned.
    """
    bound_columns = [
        "game_id",
        "period",
        "start_seconds",
        "end_seconds",
        "start_wall",
        "end_wall",
    ]
    bounds = pl.concat(
        [
            periods.select(
                *bound_columns,
                pl.col("start_wall").alias("bound"),
                pl.lit(PHASE_LIVE).alias("phase"),
            ),
            periods.select(
                *bound_columns,
                # The end marker's own second is still live
                (pl.col("end_wall") + 1).alias("bound"),
                pl.lit(PHASE_BREAK).alias("phase"),
            ),
        ]
    ).sort("game_id", "bound")
    finals = periods.group_by("game_id").agg(
        pl.col("period").max().alias("last_period"),
        pl.col("end_seconds").max().alias("total_seconds"),
    )

    placed = (
        comments.with_row_index("_order")
        .sort("game_id", "created_utc")
        .join_asof(
            bounds,
            left_on="created_utc",
            right_on="bound",
            by="game_id",
            strategy="backward",
            check_sortedness=False,
        )
        .join(finals, on="game_id", how="left")
    )
    phase = (
        pl.when(pl.col("bound").is_null())
        .then(pl.lit(PHASE_PRE))
        .when(
            (pl.col("phase") == PHASE_BREAK)
            & (pl.col("period") == pl.col("last_period"))
        )
        .then(pl.lit(PHASE_POST))
        .otherwise(pl.col("phase"))
    )
    elapsed = (pl.col("created_utc") - pl.col("start_wall")) / (
        pl.col("end_wall") - pl.col("start_wall")
    )
    live_seconds = pl.col("start_seconds") + (
        elapsed * (pl.col("end_seconds") - pl.col("start_seconds"))
    ).round(0)
    game_seconds = (
        pl.when(pl.col("phase") == PHASE_PRE)
        .then(0)
        .when(pl.col("phase") == PHASE_LIVE)
        .then(live_seconds)
        .when(pl.col("phase") == PHASE_BREAK)
        .then(pl.col("end_seconds"))
        .otherwise(pl.col("total_seconds"))
        .cast(pl.Int64)
    )
    return (
        placed.with_columns(phase.alias("phase"))
        .with_columns(
            game_seconds.alias("game_seconds"),
            pl.when(pl.col("phase").is_in([PHASE_LIVE, PHASE_BREAK]))
            .then(pl.col("period"))
            .otherwise(None)
            .alias("period"),
        )
        .sort("_order")
        .select(*comments.columns, "game_seconds", "phase", "period")
    )


def place_plays(plays: pl.DataFrame, periods: pl.DataFrame) -> pl.DataFrame:
    """
    Put plays on both clocks: game seconds from the period clock, wall clock by the line.

    Args:
        plays: Play-by-play rows with ``game_id``, ``period`` and ``clock``.
        periods: The game clock from build_periods, ``game_id`` included.

    Returns:
        The plays with ``game_seconds`` and ``wall_clock`` (epoch seconds)
        added, in the input's row order.

    Raises:
        RecapError: If a clock string does not parse, or a play's period
            has no markers.
    """
    placed = plays.with_row_index("_order").join(
        periods.select(
            "game_id",
            "period",
            "start_seconds",
            "end_seconds",
            "start_wall",
            "end_wall",
        ),
        on=["game_id", "period"],
        how="left",
    )
    unplaced = placed.filter(pl.col("start_wall").is_null())
    if unplaced.height:
        first = unplaced.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: period {first['period']} has no markers "
            f"(action {first['action_id']})"
        )
    placed = placed.with_columns(
        parse_clock_seconds(pl.col("clock")).alias("_remaining")
    )
    unparsed = placed.filter(pl.col("_remaining").is_null())
    if unparsed.height:
        first = unparsed.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: clock {first['clock']!r} does not parse "
            f"(action {first['action_id']})"
        )

    game_seconds = (
        (pl.col("end_seconds") - pl.col("_remaining")).round(0).cast(pl.Int64)
    )
    fraction = (pl.col("game_seconds") - pl.col("start_seconds")) / (
        pl.col("end_seconds") - pl.col("start_seconds")
    )
    wall_clock = (
        pl.col("start_wall")
        + (fraction * (pl.col("end_wall") - pl.col("start_wall"))).round(0)
    ).cast(pl.Int64)
    return (
        placed.with_columns(game_seconds.alias("game_seconds"))
        .with_columns(wall_clock.alias("wall_clock"))
        .sort("_order")
        .drop(
            "_order",
            "_remaining",
            "start_seconds",
            "end_seconds",
            "start_wall",
            "end_wall",
        )
    )


# --- Plays and stints -------------------------------------------------------


@dataclass(frozen=True)
class Focus:
    """The focus player as the archive names him: id, name forms, team."""

    person_id: int
    names: tuple[str, ...]  # every form a description may use, ASCII-folded
    team_id: int

    @property
    def pattern(self) -> str:
        """A regex alternation over his name forms."""
        return "(?:" + "|".join(re.escape(name) for name in self.names) + ")"


def _fold(name: str) -> str:
    """The archive's descriptions write names without diacritics."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()


def focus_identity(pbp: pl.DataFrame, person_id: int) -> Focus:
    """
    Read the focus player's archive names and team from his own rows.

    A description names a player by surname ("Jokic", folded from the
    row's "Jokić") or, when a surname is shared, by initial and surname
    ("L. James"), so both forms are kept.

    Args:
        pbp: One game's play-by-play.
        person_id: The player's stats.nba.com id (players.player_id).

    Returns:
        The Focus: the folded ``player_name`` and ``player_name_i`` the
        descriptions use for him, and the ``team_id`` his rows carry.

    Raises:
        RecapError: If he has no row in the game.
    """
    own = pbp.filter(pl.col("person_id") == person_id)
    if not own.height:
        game_id = pbp["game_id"][0] if pbp.height else "?"
        raise RecapError(f"{game_id}: player {person_id} has no action in the game")
    names = []
    for column in ("player_name", "player_name_i"):
        folded = _fold(own[column].mode().sort()[0])
        if folded and folded not in names:
            names.append(folded)
    team_id = own["team_id"].mode().sort()[0]
    return Focus(person_id, tuple(names), team_id)


def fill_scores(pbp: pl.DataFrame) -> pl.DataFrame:
    """
    Carry the running score onto every row.

    The archive writes the score only on the rows that change it; every
    other row holds an empty string. Rows are filled in action order,
    and 0 stands before the first score.

    Args:
        pbp: One game's play-by-play, any row order.

    Returns:
        The rows sorted by ``action_id`` with ``score_home`` and
        ``score_away`` as Int64 on every row.
    """

    def filled(column: str) -> pl.Expr:
        return (
            pl.when(pl.col(column) == "")
            .then(None)
            .otherwise(pl.col(column))
            .cast(pl.Int64)
            .forward_fill()
            .fill_null(0)
            .alias(column)
        )

    return pbp.sort("action_id").with_columns(
        filled("score_home"), filled("score_away")
    )


def derive_kind(pbp: pl.DataFrame, focus: Focus) -> pl.DataFrame:
    """
    Name each play's kind and flag the focus player's plays.

    Blocks and steals are read from the description, since their
    ``action_type`` is blank. A substitution names only the player going
    out in ``person_id``; the focus player's check-ins are matched on
    the description, guarded by his team so a shared surname on the
    other bench never counts. His assists sit on a teammate's made shot
    and are his plays too.

    Args:
        pbp: One game's play-by-play.
        focus: The focus player as the archive names him.

    Returns:
        The rows with ``kind`` and ``is_focus`` added.
    """
    description = pl.col("description")
    checks_in = description.str.contains(rf"^SUB: {focus.pattern} FOR ") & (
        pl.col("team_id") == focus.team_id
    )
    assists = description.str.contains(rf"\({focus.pattern} \d+ AST\)")

    kind = pl.when(pl.col("action_type") == PERIOD_ACTION_TYPE).then(
        pl.when(pl.col("sub_type") == PERIOD_START)
        .then(pl.lit(KIND_PERIOD_START))
        .otherwise(pl.lit(KIND_PERIOD_END))
    )
    for token, name in _BLANK_TYPE_KINDS:
        kind = kind.when(
            (pl.col("action_type") == "")
            & description.str.contains(token, literal=True)
        ).then(pl.lit(name))
    kind = (
        kind.when(
            (pl.col("action_type") == SUBSTITUTION_ACTION_TYPE)
            & (pl.col("person_id") == focus.person_id)
        )
        .then(pl.lit(KIND_SUB_OUT))
        .when((pl.col("action_type") == SUBSTITUTION_ACTION_TYPE) & checks_in)
        .then(pl.lit(KIND_SUB_IN))
        .otherwise(
            pl.col("action_type").replace_strict(
                ACTION_TYPE_KINDS, default=KIND_OTHER, return_dtype=pl.String
            )
        )
    )
    is_focus = (pl.col("person_id") == focus.person_id) | checks_in | assists
    return pbp.with_columns(kind.alias("kind"), is_focus.alias("is_focus"))


def pair_blocks(pbp: pl.DataFrame) -> pl.DataFrame:
    """
    Point each block and steal at the play it ended.

    A block or steal reuses the ``action_number`` of the shot or turnover
    it ends. A block borrows the shot's location, so it draws where the
    shot was taken.

    Args:
        pbp: One game's play-by-play with ``kind`` (derive_kind).

    Returns:
        The rows with ``paired_action_id`` added (null off a block or
        steal), blocks carrying their shot's coordinates.

    Raises:
        RecapError: If a block or steal shares its number with no play.
    """
    # Only a block or steal reuses a number; every other row pairs with
    # nothing, so only those rows are joined
    partners = (
        pbp.filter(pl.col("action_type") != "")
        .sort("action_id")
        .unique(subset=["game_id", "action_number"], keep="first", maintain_order=True)
        .select(
            "game_id",
            "action_number",
            pl.col("action_id").alias("paired_action_id"),
            pl.col("x_legacy").alias("_x"),
            pl.col("y_legacy").alias("_y"),
            pl.col("shot_distance").alias("_distance"),
            pl.col("action_type").is_in(SHOT_ACTION_TYPES).alias("_is_shot"),
        )
    )
    ended = pl.col("kind").is_in(["block", "steal"])
    enders = pbp.filter(ended).join(
        partners, on=["game_id", "action_number"], how="left"
    )
    unpaired = enders.filter(pl.col("paired_action_id").is_null())
    if unpaired.height:
        first = unpaired.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: {first['kind']} at action {first['action_id']} "
            f"shares its number with no play"
        )
    borrows = pl.col("_is_shot").fill_null(False)
    enders = enders.with_columns(
        pl.when(borrows)
        .then(pl.col("_x"))
        .otherwise(pl.col("x_legacy"))
        .alias("x_legacy"),
        pl.when(borrows)
        .then(pl.col("_y"))
        .otherwise(pl.col("y_legacy"))
        .alias("y_legacy"),
        pl.when(borrows)
        .then(pl.col("_distance"))
        .otherwise(pl.col("shot_distance"))
        .alias("shot_distance"),
    ).drop("_x", "_y", "_distance", "_is_shot")
    others = pbp.filter(~ended).with_columns(
        pl.lit(None, dtype=pl.Int64).alias("paired_action_id")
    )
    return pl.concat([others, enders]).sort("action_id")


def parse_running_totals(plays: pl.DataFrame, focus: Focus) -> pl.DataFrame:
    """
    Read the focus player's running line off his own descriptions.

    Points, rebounds, blocks, steals, fouls and turnovers sit in the
    parentheses of his rows; assists sit on a teammate's made shot under
    his name. Each total carries forward to his next play and is null on
    every other row and before his first value.

    Args:
        plays: The plays in action order, with ``is_focus`` and ``kind``.
        focus: The focus player as the archive names him.

    Returns:
        The plays with TOTAL_COLUMNS added as nullable Int64.
    """
    own = pl.col("person_id") == focus.person_id
    description = pl.col("description")

    def own_count(pattern: str) -> pl.Expr:
        return pl.when(own).then(description.str.extract(pattern, 1).cast(pl.Int64))

    totals = {name: own_count(pattern) for name, pattern in _TOTAL_PATTERNS.items()}
    totals["reb"] = own_count(_OFFENSIVE_REBOUNDS) + own_count(_DEFENSIVE_REBOUNDS)
    totals["ast"] = description.str.extract(rf"\({focus.pattern} (\d+) AST\)", 1).cast(
        pl.Int64
    )
    totals["tov"] = pl.when(own & (pl.col("kind") == "turnover")).then(
        description.str.extract(_PERSONAL_COUNT, 1).cast(pl.Int64)
    )
    totals["pf"] = pl.when(own & (pl.col("kind") == "foul")).then(
        description.str.extract(_PERSONAL_COUNT, 1).cast(pl.Int64)
    )
    return plays.with_columns(
        pl.when(pl.col("is_focus"))
        .then(totals[name].forward_fill())
        .otherwise(None)
        .alias(name)
        for name in TOTAL_COLUMNS
    )


def slice_plays(pbp: pl.DataFrame, periods: pl.DataFrame, focus: Focus) -> pl.DataFrame:
    """
    The plays a recap ships, on both clocks, in RECAP_PLAYS_SCHEMA's shape.

    The focus player's plays (check-ins and assists included), both
    teams' shots, the period markers and the timeouts, with the score
    filled onto every row before the slice so nothing kept is missing
    the points a dropped free throw scored.

    Args:
        pbp: One game's play-by-play.
        periods: The game's clock (build_periods), ``game_id`` included.
        focus: The focus player as the archive names him.

    Returns:
        The slice in action order, columns as RECAP_PLAYS_SCHEMA plus
        ``game_id`` in front.

    Raises:
        RecapError: From pair_blocks and place_plays.
    """
    prepared = pair_blocks(derive_kind(fill_scores(pbp), focus))
    kept = prepared.filter(
        pl.col("is_focus")
        | pl.col("action_type").is_in(SHOT_ACTION_TYPES)
        | pl.col("kind").is_in(_SLICE_KINDS)
    )
    placed = parse_running_totals(place_plays(kept, periods), focus)
    made = (
        pl.when(pl.col("shot_result") == "Made")
        .then(True)
        .when(pl.col("shot_result") == "Missed")
        .then(False)
        .otherwise(None)
        .cast(pl.Boolean)
    )
    return placed.with_columns(made.alias("made")).select(
        "game_id", *RECAP_PLAYS_SCHEMA.names()
    )


def build_stints(plays: pl.DataFrame, periods: pl.DataFrame) -> pl.DataFrame:
    """
    The focus player's on-court intervals, in game seconds.

    Lineups change at period breaks without a substitution row, so each
    period's opening state is inferred: on the floor if his first
    substitution in the period takes him off, off if it brings him on,
    and with no substitution at all, on if he recorded any play. From
    there the substitutions open and close intervals; an interval open
    at the buzzer closes on it.

    Args:
        plays: The recap's plays (slice_plays) with ``is_focus``.
        periods: The game's clock (build_periods).

    Returns:
        RECAP_STINTS_SCHEMA rows in game order.
    """
    events = (
        plays.filter(pl.col("is_focus") & (pl.col("kind") != KIND_PERIOD_START))
        .sort("action_id")
        .select("period", "kind", "game_seconds")
        .rows()
    )
    stints: list[tuple[int, int, int]] = []
    for period, start, end in (
        periods.sort("period").select("period", "start_seconds", "end_seconds").rows()
    ):
        own = [(kind, seconds) for p, kind, seconds in events if p == period]
        subs = [(kind, seconds) for kind, seconds in own if kind in SUB_KINDS]
        if subs:
            on_court = subs[0][0] == KIND_SUB_OUT
        else:
            on_court = bool(own)
        opened = start if on_court else None
        for kind, seconds in subs:
            if kind == KIND_SUB_OUT and opened is not None:
                stints.append((period, opened, seconds))
                opened = None
            elif kind == KIND_SUB_IN and opened is None:
                opened = seconds
        if opened is not None:
            stints.append((period, opened, end))
    return pl.DataFrame(stints, schema=RECAP_STINTS_SCHEMA, orient="row")


# --- Comments ---------------------------------------------------------------


def select_comments(
    aligned: pl.DataFrame, focus_player: str, players: pl.DataFrame
) -> pl.DataFrame:
    """
    The comments frame: every aligned comment, bodies by rule.

    Every comment names its target by the Player dimension's id, null
    when unattributed. A body is kept for the focus player's comments
    and for the room's top-voted per wall-clock bucket (the highest
    scores, ties by id); every other body is null. A kept body is
    verbatim.

    Args:
        aligned: Fact rows in the live threads after align_comments:
            comment_id, link_id, created_utc, sentiment, score, fan_team,
            attributed_player, body, game_seconds, phase.
        focus_player: The recap's attributed_player.
        players: The Player dimension (attributed_player, player_id).

    Returns:
        RECAP_COMMENTS_SCHEMA rows sorted by created_utc, then comment_id.
    """
    is_focus = (pl.col("attributed_player") == focus_player).fill_null(False)
    bucket = pl.col("created_utc") // RECAP_ROOM_BUCKET_SECONDS
    ranked = (
        aligned.join(
            players.select("attributed_player", "player_id"),
            on="attributed_player",
            how="left",
        )
        .with_columns(is_focus.alias("is_focus"), bucket.alias("_bucket"))
        .sort(["score", "comment_id"], descending=[True, False], nulls_last=True)
        .with_columns(pl.int_range(pl.len()).over("_bucket", "is_focus").alias("_rank"))
    )
    keeps_body = pl.col("is_focus") | (pl.col("_rank") < RECAP_ROOM_BODIES_PER_BUCKET)
    return (
        ranked.with_columns(
            pl.when(keeps_body).then(pl.col("body")).otherwise(None).alias("body"),
            pl.col("link_id").alias("post_id"),
        )
        .sort("created_utc", "comment_id")
        .select(RECAP_COMMENTS_SCHEMA.names())
    )


def period_counts(
    aligned: pl.DataFrame, focus_player: str, n_periods: int
) -> dict[str, PeriodCounts]:
    """
    The focus player's sentiment counts per period, zero-filled.

    Live and break comments count in their period; pre and post do not.

    Args:
        aligned: Fact rows after align_comments, with attributed_player,
            sentiment and period.
        focus_player: The recap's attributed_player.
        n_periods: How many periods the game had.

    Returns:
        Period number as a string -> counts, "1" through n_periods.
    """
    counted = (
        aligned.filter(
            (pl.col("attributed_player") == focus_player)
            & pl.col("period").is_not_null()
        )
        .group_by("period", "sentiment")
        .len()
    )
    counts = {
        str(period): {name: 0 for name in SENTIMENTS}
        for period in range(1, n_periods + 1)
    }
    for period, sentiment, n in counted.rows():
        if sentiment in SENTIMENTS:
            counts[str(period)][sentiment] = n
    return counts  # type: ignore[return-value]


def swing(by_period: dict[str, PeriodCounts]) -> float:
    """
    Negative share in the last period minus the first, as the index hook.

    Args:
        by_period: period_counts() output.

    Returns:
        The change in negative share between the first and the last
        period with any comment; 0.0 with fewer than two such periods.
    """

    def total(counts: PeriodCounts) -> int:
        return counts["neg"] + counts["pos"] + counts["neu"]

    spoken = [
        by_period[key] for key in sorted(by_period, key=int) if total(by_period[key])
    ]
    if len(spoken) < 2:
        return 0.0
    return spoken[-1]["neg"] / total(spoken[-1]) - spoken[0]["neg"] / total(spoken[0])


# --- The clock's error, season-wide ------------------------------------------


def read_game_clock(
    game_id: str, game_dates: pl.DataFrame, pbp_dir: Path
) -> tuple[pl.DataFrame, pl.DataFrame] | None:
    """
    One banked game's play-by-play and the clock its markers build.

    Args:
        game_id: The game.
        game_dates: ``game_id`` and ``game_date`` for the game.
        pbp_dir: The season's play-by-play directory.

    Returns:
        ``(pbp, periods)``, or None when the archive is not banked or its
        markers do not build a clock (logged).
    """
    path = play_by_play_path(pbp_dir, game_id)
    if not path.exists():
        return None
    pbp = pl.read_parquet(path)
    try:
        return pbp, build_periods(pbp, game_dates)
    except RecapError as e:
        logger.warning(f"no clock for {game_id}, skipped: {e}")
        return None


def anchor_candidates(
    pbp: pl.DataFrame, periods: pl.DataFrame, players: pl.DataFrame
) -> pl.DataFrame:
    """
    A game's anchor candidates: every tracked player's blocks, steals and made dunks.

    Args:
        pbp: One game's play-by-play.
        periods: The game's clock (build_periods).
        players: The Player dimension (attributed_player, player_id).

    Returns:
        ANCHOR_CANDIDATE_SCHEMA rows: each play on both clocks, its player
        as the fact names him, and the third of its period it fell in.
    """
    description = pl.col("description")
    kind = pl.when(
        (pl.col("action_type") == MADE_SHOT_ACTION_TYPE)
        & pl.col("sub_type").str.contains(DUNK_SUB_TYPE, literal=True)
    ).then(pl.lit(KIND_DUNK))
    for token, name in _BLANK_TYPE_KINDS:
        kind = kind.when(
            (pl.col("action_type") == "")
            & description.str.contains(token, literal=True)
        ).then(pl.lit(name))
    plays = (
        pbp.with_columns(kind.alias("kind"))
        .filter(pl.col("kind").is_not_null())
        .join(
            players.select(pl.col("player_id").alias("person_id"), "attributed_player"),
            on="person_id",
            how="inner",
        )
    )
    placed = place_plays(plays, periods).join(
        periods.select("game_id", "period", "start_seconds", "end_seconds"),
        on=["game_id", "period"],
        how="left",
    )
    third = (
        (pl.col("game_seconds") - pl.col("start_seconds"))
        * 3
        // (pl.col("end_seconds") - pl.col("start_seconds"))
    ).clip(0, 2) + 1
    return placed.with_columns(third.cast(pl.Int64).alias("third")).select(
        ANCHOR_CANDIDATE_SCHEMA.names()
    )


def named_reactions(fact: pl.DataFrame, threads: pl.DataFrame) -> pl.DataFrame:
    """
    The live-thread comments that name an anchor kind, by the published vocabulary.

    Args:
        fact: Usable fact rows (link_id, created_utc, attributed_player, body).
        threads: The live threads (post_id, game_id).

    Returns:
        One row per (comment, kind it names): game_id, attributed_player,
        kind, created_utc. Unattributed comments name no one's play.
    """
    room = (
        fact.filter(pl.col("attributed_player").is_not_null())
        .join(threads, left_on="link_id", right_on="post_id", how="inner")
        .select(
            "game_id",
            "attributed_player",
            "created_utc",
            pl.col("body").str.to_lowercase().alias("_body"),
        )
    )
    return pl.concat(
        [
            room.filter(pl.col("_body").str.contains(pattern)).select(
                "game_id",
                "attributed_player",
                pl.lit(kind).alias("kind"),
                "created_utc",
            )
            for kind, pattern in RECAP_ANCHOR_VOCABULARY.items()
        ]
    )


def match_anchors(candidates: pl.DataFrame, reactions: pl.DataFrame) -> pl.DataFrame:
    """
    Give each candidate the burst of comments that named it, if any.

    A burst is one wall-clock minute of comments about the play's player
    naming its kind. Bursts within the published window of a play are
    its reactions, but a burst counts for one play only, the nearest to
    its first comment; each play then keeps its largest burst, the
    earliest on a tie. A play is an anchor when that burst reaches the
    published floor, and its offset is the burst's first comment minus
    the play's mapped wall clock.

    Args:
        candidates: anchor_candidates() rows, any number of games.
        reactions: named_reactions() rows.

    Returns:
        The candidates with reaction_n, first_reaction_utc, offset_seconds
        (null unless accepted) and accepted, sorted by game and action.
    """
    bursts = reactions.group_by(
        "game_id",
        "attributed_player",
        "kind",
        (pl.col("created_utc") // 60 * 60).alias("minute"),
    ).agg(
        pl.len().cast(pl.Int64).alias("reaction_n"),
        pl.col("created_utc").min().alias("first_reaction_utc"),
    )
    burst_key = ["game_id", "attributed_player", "kind", "minute"]
    best = (
        candidates.join(bursts, on=["game_id", "attributed_player", "kind"])
        .filter(
            (pl.col("minute") - pl.col("wall_clock")).abs()
            <= RECAP_ANCHOR_WINDOW_SECONDS
        )
        .with_columns(
            (pl.col("first_reaction_utc") - pl.col("wall_clock")).abs().alias("_gap")
        )
        .sort("_gap", "action_id")
        .unique(subset=burst_key, keep="first", maintain_order=True)
        .sort(["reaction_n", "minute"], descending=[True, False])
        .unique(subset=["game_id", "action_id"], keep="first", maintain_order=True)
        .select("game_id", "action_id", "reaction_n", "first_reaction_utc")
    )
    accepted = pl.col("reaction_n") >= RECAP_ANCHOR_MIN_REACTIONS
    return (
        candidates.join(best, on=["game_id", "action_id"], how="left")
        .with_columns(pl.col("reaction_n").fill_null(0))
        .with_columns(
            accepted.alias("accepted"),
            pl.when(accepted)
            .then(pl.col("first_reaction_utc") - pl.col("wall_clock"))
            .alias("offset_seconds"),
        )
        .sort("game_id", "action_id")
    )


def alignment_figures(anchors: pl.DataFrame) -> AlignmentFigures:
    """
    Summarize matched candidates as the published alignment figures.

    Quantiles are observed offsets (nearest rank), never interpolated.

    Args:
        anchors: match_anchors() rows (game_id, accepted, offset_seconds).

    Returns:
        Candidates, anchors, games with one, and the median and quartile
        offsets in seconds; the offsets are None with no anchor.
    """
    accepted = anchors.filter(pl.col("accepted"))
    offsets = accepted["offset_seconds"]

    def quantile(q: float) -> int | None:
        if not accepted.height:
            return None
        return int(offsets.quantile(q, interpolation="nearest"))

    return {
        "candidates": anchors.height,
        "anchors": accepted.height,
        "games": accepted["game_id"].n_unique(),
        "median_offset_seconds": quantile(0.5),
        "p25_offset_seconds": quantile(0.25),
        "p75_offset_seconds": quantile(0.75),
    }


def unmeasured_alignment() -> AlignmentFigures:
    """The figures of a season that curates no recap: nothing measured."""
    return {
        "candidates": 0,
        "anchors": 0,
        "games": 0,
        "median_offset_seconds": None,
        "p25_offset_seconds": None,
        "p75_offset_seconds": None,
    }


def measure_alignment(
    fact: pl.DataFrame,
    posts: pl.DataFrame,
    games: pl.DataFrame,
    players: pl.DataFrame,
    pbp_dir: Path,
) -> tuple[pl.DataFrame, AlignmentFigures]:
    """
    Measure the game clock against the room's reactions, over every threaded game.

    The clock is one method for every game, so its error is measured
    once, season-wide: a single game rarely draws enough named reactions
    to measure its own. The anchors measure the clock; nothing is moved.

    Args:
        fact: The usable fact rows, at least those in game threads.
        posts: The Post bridge.
        games: The Game dimension (game_id, game_date).
        players: The Player dimension (attributed_player, player_id).
        pbp_dir: The season's play-by-play directory.

    Returns:
        Every candidate matched (match_anchors) and the figures
        (alignment_figures). The median offset per third of the period
        is logged: the straight line's error is not even across it.
    """
    threads = posts.filter(
        (pl.col("post_type") == GAME_THREAD) & pl.col("game_id").is_not_null()
    ).select("post_id", "game_id")
    game_dates = games.select("game_id", "game_date")
    frames = [ANCHOR_CANDIDATE_SCHEMA.to_frame()]
    skipped = 0
    for game_id in sorted(threads["game_id"].unique().to_list()):
        banked = read_game_clock(game_id, game_dates, pbp_dir)
        if banked is None:
            skipped += 1
            continue
        frames.append(anchor_candidates(*banked, players))
    anchors = match_anchors(pl.concat(frames), named_reactions(fact, threads))
    figures = alignment_figures(anchors)

    by_third = (
        anchors.filter(pl.col("accepted"))
        .group_by("third")
        .agg(pl.col("offset_seconds").median().round(0).cast(pl.Int64))
        .sort("third")
        .rows()
    )
    logger.info(
        f"Alignment: {figures['anchors']:,} anchors of {figures['candidates']:,} "
        f"candidates in {figures['games']:,} games ({skipped:,} without a clock); "
        f"median offset {figures['median_offset_seconds']} s "
        f"(p25 {figures['p25_offset_seconds']}, p75 {figures['p75_offset_seconds']}); "
        f"median by third of the period {dict(by_third)}"
    )
    return anchors, figures


# --- The document -----------------------------------------------------------


@dataclass(frozen=True)
class ResolvedSpec:
    """A curated recap with its identities resolved against the frames."""

    game_id: str
    slug: str
    attributed_player: str
    player_id: int
    thread_ids: tuple[str, ...]
    room_n: int
    pbp_path: Path

    @property
    def key(self) -> str:
        return recap_key(self.game_id, self.slug)


@dataclass(frozen=True)
class RecapStamps:
    """What every recap header carries about the build it came from."""

    season: str
    generated_at: str
    config_versions: dict[str, str]
    classifiers: dict[str, ClassifierIdentity]


@dataclass(frozen=True)
class RecapDocument:
    """One built recap: its header, its frames and its registry entry."""

    key: str
    header: RecapHeader
    frames: dict[str, pl.DataFrame]
    entry: RecapEntry


def recap_key(game_id: str, slug: str) -> str:
    """The recap's key, the file's stem and the registry's key."""
    return f"{game_id}-{slug}"


def resolve_recap_specs(
    specs: Sequence[RecapSpec],
    games: pl.DataFrame,
    players: pl.DataFrame,
    posts: pl.DataFrame,
    pbp_dir: Path,
) -> list[ResolvedSpec]:
    """
    Check every curated recap against the frames and resolve its identities.

    Args:
        specs: The curation (load_recaps_config).
        games: The Game dimension (game_id).
        players: The Player dimension (slug, attributed_player, player_id).
        posts: The Post bridge (post_id, post_type, game_id, num_comments).
        pbp_dir: The season's play-by-play directory.

    Returns:
        One ResolvedSpec per entry, in page order.

    Raises:
        RecapError: If a game is not in the dimension, a slug is not a
            player, a game has no live thread, or its play-by-play is
            not banked. The message names the entry and the cause.
    """
    game_ids = set(games["game_id"].to_list())
    by_slug = {
        slug: (player, player_id)
        for slug, player, player_id in players.select(
            "slug", "attributed_player", "player_id"
        ).rows()
    }
    live = posts.filter(pl.col("post_type") == GAME_THREAD)
    resolved = []
    for spec in specs:
        where = f"recap {spec.game_id} / {spec.slug}"
        if spec.game_id not in game_ids:
            raise RecapError(f"{where}: game is not in the Game dimension")
        if spec.slug not in by_slug:
            raise RecapError(f"{where}: slug is not in the Player dimension")
        threads = live.filter(pl.col("game_id") == spec.game_id)
        if not threads.height:
            raise RecapError(f"{where}: game has no live game thread")
        path = play_by_play_path(pbp_dir, spec.game_id)
        if not path.exists():
            raise RecapError(f"{where}: play-by-play is not banked at {path}")
        player, player_id = by_slug[spec.slug]
        resolved.append(
            ResolvedSpec(
                game_id=spec.game_id,
                slug=spec.slug,
                attributed_player=player,
                player_id=int(player_id),
                thread_ids=tuple(threads["post_id"].to_list()),
                room_n=int(threads["num_comments"].sum()),
                pbp_path=path,
            )
        )
    return resolved


def stint_minutes(stints: pl.DataFrame) -> int:
    """Minutes on the floor, rounded, from the stints frame."""
    if not stints.height:
        return 0
    return int(round((stints["end_seconds"] - stints["start_seconds"]).sum() / 60))


def build_recap(
    spec: ResolvedSpec,
    *,
    fact: pl.DataFrame,
    posts: pl.DataFrame,
    games: pl.DataFrame,
    player_games: pl.DataFrame,
    players: pl.DataFrame,
    pbp: pl.DataFrame,
    stamps: RecapStamps,
) -> RecapDocument:
    """
    Build one recap: the clock, the plays, the comments, the measurements.

    Args:
        spec: The resolved curation entry.
        fact: The usable fact rows (load_attributed_frame or a subset
            covering the game's live threads).
        posts: The Post bridge.
        games: The Game dimension (game_id, game_date).
        player_games: The box-score lines (game_id, attributed_player,
            minutes).
        players: The Player dimension (attributed_player, player_id).
        pbp: The game's play-by-play (load_play_by_play).
        stamps: The build's lineage for the header.

    Returns:
        The document, every frame validated against its schema.

    Raises:
        RecapError: From the alignment and the plays, or if the focus
            player has no box-score line in the game.
    """
    periods = build_periods(pbp, games.select("game_id", "game_date"))
    focus = focus_identity(pbp, spec.player_id)
    plays = slice_plays(pbp, periods, focus)
    stints = build_stints(plays, periods)

    aligned = align_comments(
        fact.filter(pl.col("link_id").is_in(list(spec.thread_ids))).with_columns(
            pl.lit(spec.game_id).alias("game_id")
        ),
        periods,
    )
    comments = select_comments(aligned, spec.attributed_player, players)
    threads = (
        posts.filter(pl.col("post_id").is_in(list(spec.thread_ids)))
        .join(
            comments.group_by("post_id").agg(pl.len().alias("comment_n")),
            on="post_id",
            how="left",
        )
        .with_columns(pl.col("comment_n").fill_null(0).cast(pl.Int64))
        .sort("created_utc")
        .select(RECAP_THREADS_SCHEMA.names())
    )

    line = player_games.filter(
        (pl.col("game_id") == spec.game_id)
        & (pl.col("attributed_player") == spec.attributed_player)
    )
    if not line.height:
        raise RecapError(f"recap {spec.key}: no box-score line for the focus player")
    box_minutes = int(line["minutes"][0])
    minutes_diff = stint_minutes(stints) - box_minutes
    if minutes_diff:
        # An inferred period start is where stints go wrong: a period
        # played with no substitution and no play reads as bench
        logger.warning(
            f"recap {spec.key}: {stint_minutes(stints)} stint minutes against "
            f"{box_minutes} in the box score ({minutes_diff:+d})"
        )

    n_periods = int(periods["period"].max())
    by_period = period_counts(aligned, spec.attributed_player, n_periods)
    frames = {
        "periods": periods.select(RECAP_PERIODS_SCHEMA.names()),
        "threads": threads,
        "stints": stints,
        "plays": plays.select(RECAP_PLAYS_SCHEMA.names()),
        "comments": comments,
    }
    for name in RECAP_FRAME_SCHEMAS:
        validate_schema(frames[name], RECAP_FRAME_SCHEMAS[name], f"{spec.key}.{name}")
        validate_nullability(
            frames[name], RECAP_NULLABLE_COLUMNS[name], f"{spec.key}.{name}"
        )

    header: RecapHeader = {
        "schema_version": SCHEMA_VERSION,
        "season": stamps.season,
        "generated_at": stamps.generated_at,
        "game_id": spec.game_id,
        "attributed_player": spec.attributed_player,
        "player_id": spec.player_id,
        "slug": spec.slug,
        "config_versions": dict(stamps.config_versions),
        "classifiers": {
            stage: stamps.classifiers[stage]
            for stage in CLASSIFIER_STAGES
            if stage in stamps.classifiers
        },
    }
    entry: RecapEntry = {
        "file": recap_file(spec.key),
        "rows": comments.height,
        "game_id": spec.game_id,
        "attributed_player": spec.attributed_player,
        "player_id": spec.player_id,
        "slug": spec.slug,
        "live_n": int(comments["is_focus"].sum()),
        "room_n": spec.room_n,
        "by_period": by_period,
        "swing": swing(by_period),
        "minutes_diff": minutes_diff,
        "population": RECAP_POPULATION,
    }
    return RecapDocument(spec.key, header, frames, entry)


def serialize_recap(doc: RecapDocument) -> dict:
    """
    The document as JSON data: the header, then each frame as column arrays.

    Args:
        doc: A built recap.

    Returns:
        ``{"header": ..., "frames": {name: {column: [values]}}}``,
        frames in RECAP_FRAME_SCHEMAS order, nulls as JSON null.
    """
    return {
        "header": dict(doc.header),
        "frames": {
            name: doc.frames[name].to_dict(as_series=False)
            for name in RECAP_FRAME_SCHEMAS
        },
    }


def write_recap(doc: RecapDocument, dashboard_dir: Path) -> tuple[Path, int]:
    """
    Write a recap under the dashboard directory, atomically.

    Args:
        doc: A built recap.
        dashboard_dir: The season's dashboard directory.

    Returns:
        The path written and its size in bytes.
    """
    path = dashboard_dir / recap_file(doc.key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + _TMP_SUFFIX)
    tmp.write_bytes(encode_recap(doc))
    os.replace(tmp, path)
    return path, path.stat().st_size


def encode_recap(doc: RecapDocument) -> bytes:
    """The bytes write_recap puts on disk: compact UTF-8 JSON."""
    return json.dumps(
        serialize_recap(doc), separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


# --- The candidate scan -----------------------------------------------------


def scan_candidates(
    fact: pl.DataFrame,
    posts: pl.DataFrame,
    games: pl.DataFrame,
    players: pl.DataFrame,
    pbp_dir: Path,
    *,
    min_live_n: int = SCAN_MIN_LIVE_N,
) -> tuple[pl.DataFrame, list[str]]:
    """
    Rank every (game, player) with a live thread by the swing in his negative share.

    The Player x Game x Period grain over every threaded game, sorted by
    the size of the swing, as the input to curation. Alignment is the
    recaps' own, so the scan and a recap can never disagree.

    Args:
        fact: The usable fact rows, at least those in game threads.
        posts: The Post bridge.
        games: The Game dimension (game_id, game_date, home_team, away_team).
        players: The Player dimension (attributed_player, slug).
        pbp_dir: The season's play-by-play directory.
        min_live_n: Fewest live-thread comments a pair needs to rank.

    Returns:
        The candidates, one row per (game, player), sorted by |swing|
        descending, with a ``curation`` column holding the recaps.yaml
        entry to paste (a spreadsheet would read the bare game id as a
        number and drop its leading zero), and the ids of games skipped
        for a missing or defective play-by-play.
    """
    threads = posts.filter(
        (pl.col("post_type") == GAME_THREAD) & pl.col("game_id").is_not_null()
    ).select("post_id", "game_id")
    game_dates = games.select("game_id", "game_date")
    periods: list[pl.DataFrame] = []
    skipped: list[str] = []
    for game_id in sorted(threads["game_id"].unique().to_list()):
        banked = read_game_clock(game_id, game_dates, pbp_dir)
        if banked is None:
            skipped.append(game_id)
            continue
        periods.append(banked[1])
    if not periods:
        return pl.DataFrame(), skipped
    clock = pl.concat(periods)

    aligned = align_comments(
        fact.filter(pl.col("attributed_player").is_not_null())
        .join(threads, left_on="link_id", right_on="post_id", how="inner")
        .filter(pl.col("game_id").is_in(clock["game_id"].unique().to_list())),
        clock,
    ).filter(pl.col("period").is_not_null())
    per_period = (
        aligned.group_by("game_id", "attributed_player", "period")
        .agg(
            pl.len().cast(pl.Int64).alias("n"),
            (pl.col("sentiment") == "neg").sum().cast(pl.Int64).alias("neg"),
        )
        .with_columns((pl.col("neg") / pl.col("n")).alias("neg_share"))
        .sort("game_id", "attributed_player", "period")
    )
    candidates = (
        per_period.group_by("game_id", "attributed_player", maintain_order=True)
        .agg(
            pl.col("n").sum().alias("live_n"),
            pl.col("neg_share").first().alias("first_neg_share"),
            pl.col("neg_share").last().alias("last_neg_share"),
            pl.concat_str(
                pl.lit("p"),
                pl.col("period").cast(pl.String),
                pl.lit(":"),
                pl.col("neg_share").round(3).cast(pl.String),
            )
            .str.join(";")
            .alias("neg_shares"),
        )
        .filter(pl.col("live_n") >= min_live_n)
        .with_columns(
            (pl.col("last_neg_share") - pl.col("first_neg_share")).alias("swing")
        )
        .join(
            games.select("game_id", "game_date", "home_team", "away_team"),
            on="game_id",
            how="left",
        )
        .join(
            players.select("attributed_player", "slug"),
            on="attributed_player",
            how="left",
        )
        .sort(pl.col("swing").abs(), descending=True)
        .with_columns(
            pl.format(
                '- {game_id: "{}", slug: {}}', pl.col("game_id"), pl.col("slug")
            ).alias("curation")
        )
        .select(
            "game_id",
            "game_date",
            "home_team",
            "away_team",
            "attributed_player",
            "slug",
            "live_n",
            "first_neg_share",
            "last_neg_share",
            "swing",
            "neg_shares",
            "curation",
        )
    )
    return candidates, skipped


def write_recaps(documents: Sequence[RecapDocument], dashboard_dir: Path) -> list[Path]:
    """
    Write every built recap under the dashboard and remove any that is no longer curated.

    A recap dropped from the curation must not linger beside the
    registry: the publish step ships only what the manifest names, and a
    local stray would outlive its entry.

    Args:
        documents: The built recaps, in page order.
        dashboard_dir: The season's dashboard directory.

    Returns:
        The paths written, in page order.
    """
    written = []
    for doc in documents:
        path, size = write_recap(doc, dashboard_dir)
        logger.info(f"Wrote {path} ({size:,} bytes)")
        written.append(path)
    recaps_dir = dashboard_dir / RECAPS_SUBDIR
    if recaps_dir.exists():
        for stale in sorted(recaps_dir.glob("*.json")):
            if stale not in written:
                stale.unlink()
                logger.info(f"Removed {stale}: no longer curated")
    return written
