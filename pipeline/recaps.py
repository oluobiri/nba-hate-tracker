"""
Recaps: a game's live thread replayed against its play-by-play.

A recap places one game's plays and one player's comments on a shared
clock. The feed stamps every action with the time it was scored, so a
play's wall clock is read, not modeled: a comment maps to game seconds
by interpolation between the two rows either side of it on wall clock,
so a stoppage is flat wherever the feed logs a row on its frozen second
(the substitutions at a timeout's end) and otherwise spread over the few
seconds of play to the next row. Comments posted during a break pin to
the break; comments before tip-off and after the buzzer keep their
phase. The plays are the feed's rows whole and the stints are read from
its substitutions. What the room's reactions measure, once per season,
is how long the room takes to react; nothing is moved by it.

The feed is the game as scored on the night. Corrections made
afterwards reach the box score and never the feed; a recap keeps the
night-of version, which is what the room reacted to.

Every function here is a frame transform; the feed and the fact are
read at the edges by the aggregation stage.
"""

import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from pipeline.nba_stats import play_by_play_path
from pipeline.posts import GAME_THREAD
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
    ClassifierIdentity,
    PeriodCounts,
    ReactionLag,
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
GAME_ACTION_TYPE = "game"  # the feed's closing row, after the last period end
PHASE_PRE, PHASE_LIVE, PHASE_BREAK, PHASE_POST = "pre", "live", "break", "post"

# The feed's timestamp, e.g. "2026-05-31T00:23:08.2Z": UTC, to a tenth
_TIMESTAMP = "%Y-%m-%dT%H:%M:%S%.fZ"
# The feed's clock, e.g. "PT11M21.00S": time remaining in the period.
_CLOCK = r"^PT(?P<minutes>\d+)M(?P<seconds>\d+(?:\.\d+)?)S$"
# No period takes longer than this on the wall; a longer one has bad stamps
MAX_PERIOD_WALL_SECONDS = 90 * 60

PERIOD_COLUMNS = [
    "period",
    "start_seconds",
    "end_seconds",
    "start_wall",
    "end_wall",
    "start_action_number",
    "end_action_number",
]


# --- The plays --------------------------------------------------------------

# Field goals, heaves included: a heave is a shot the feed credits to
# the team only
SHOT_ACTION_TYPES = ("2pt", "3pt", "heave")
SUBSTITUTION_ACTION_TYPE = "substitution"
SUB_IN_SUB_TYPE, SUB_OUT_SUB_TYPE = "in", "out"
KIND_PERIOD_START, KIND_PERIOD_END = "period_start", "period_end"
KIND_SUB_IN, KIND_SUB_OUT, KIND_OTHER = "sub_in", "sub_out", "other"
KIND_BLOCK, KIND_STEAL, KIND_HEAVE = "block", "steal", "heave"
KIND_EJECTION = "ejection"
ACTION_TYPE_KINDS = {
    "2pt": "shot",
    "3pt": "shot",
    "heave": KIND_HEAVE,
    "freethrow": "free_throw",
    "rebound": "rebound",
    "turnover": "turnover",
    "foul": "foul",
    "timeout": "timeout",
    "jumpball": "jump_ball",
    "violation": "violation",
    "ejection": KIND_EJECTION,
    "block": KIND_BLOCK,
    "steal": KIND_STEAL,
}
SHOT_VALUES = {"3pt": 3, "2pt": 2, "freethrow": 1}
SUB_KINDS = (KIND_SUB_IN, KIND_SUB_OUT)
# A block or steal follows the play it ended, which names the ender here
_ENDER_FIELDS = {KIND_BLOCK: "block_person_id", KIND_STEAL: "steal_person_id"}
# What a block borrows from the shot it ended
_SHOT_LOCATION = ("x", "y", "shot_distance")

# --- The stints -------------------------------------------------------------

FOUL_ACTION_TYPE = "foul"
TECHNICAL_SUB_TYPE = "technical"
FLOOR_SIZE = 5  # players a team has on the floor
STINT_MINUTES_SCHEMA = pl.Schema(
    {"person_id": pl.Int64, "team_tricode": pl.String, "minutes": pl.Int64}
)
FLOOR_GAP_SCHEMA = pl.Schema(
    {
        "team_tricode": pl.String,
        "start_seconds": pl.Int64,
        "end_seconds": pl.Int64,
        "on_floor": pl.Int64,
    }
)


# --- Comments, anchors, the document ---------------------------------------

SENTIMENTS = ("neg", "pos", "neu")
# A reaction anchor: a tracked player's block, steal or made dunk that
# comments about him name, by RECAP_ANCHOR_VOCABULARY, within a minute
DUNK_SUB_TYPE = "DUNK"
KIND_DUNK = "dunk"
ANCHOR_CANDIDATE_SCHEMA = pl.Schema(
    {
        "game_id": pl.String,
        "action_number": pl.Int64,
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
    Seconds remaining in the period from the feed's clock string.

    Args:
        clock: A String column of "PT<m>M<s>S" values.

    Returns:
        A Float64 expression; null where the string does not match.
    """
    parts = clock.str.extract_groups(_CLOCK)
    return parts.struct.field("minutes").cast(pl.Int64) * 60 + parts.struct.field(
        "seconds"
    ).cast(pl.Float64)


def stamp_wall_clock(pbp: pl.DataFrame) -> pl.DataFrame:
    """
    Every row's wall clock from its own timestamp, monotone in feed order.

    The feed stamps an action when it was scored, to a tenth of a
    second, and a few rows are stamped earlier than the row before
    them. Order is the feed's: a row stamped earlier than its
    predecessor takes the predecessor's second.

    Args:
        pbp: Play-by-play rows (LIVE_PLAY_BY_PLAY_SCHEMA), one or more games.

    Returns:
        The rows in feed order (game, then ``order_number``) with
        ``wall_clock`` (epoch seconds) added.

    Raises:
        RecapError: If a timestamp does not parse.
    """
    stamped = pbp.sort("game_id", "order_number").with_columns(
        pl.col("time_actual")
        .str.to_datetime(_TIMESTAMP, time_zone="UTC", strict=False)
        .dt.epoch("s")
        .alias("_stamp")
    )
    unparsed = stamped.filter(pl.col("_stamp").is_null())
    if unparsed.height:
        first = unparsed.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: timestamp {first['time_actual']!r} does not parse "
            f"(action {first['action_number']})"
        )
    return stamped.with_columns(
        pl.col("_stamp").cum_max().over("game_id").alias("wall_clock")
    ).drop("_stamp")


def build_periods(pbp: pl.DataFrame) -> pl.DataFrame:
    """
    The game clock of one or more games from their period markers.

    Each period's start and end marker gives its wall-clock bounds from
    the markers' own timestamps; game seconds accumulate across periods
    (720 each in regulation, 300 in overtime).

    Args:
        pbp: Play-by-play rows after stamp_wall_clock, one or more games.

    Returns:
        One row per (game_id, period): ``game_id`` then PERIOD_COLUMNS,
        sorted by game and period.

    Raises:
        RecapError: If a period lacks a start or an end, a marker
            repeats, periods are not 1..N, a period ends before it
            starts, a period starts before the previous one ended, or a
            period's wall length is shorter than its game length or
            longer than MAX_PERIOD_WALL_SECONDS.
    """
    markers = pbp.filter(pl.col("action_type") == PERIOD_ACTION_TYPE).select(
        "game_id", "period", "sub_type", "action_number", "wall_clock"
    )
    repeated = (
        markers.group_by("game_id", "period", "sub_type")
        .len()
        .filter(pl.col("len") > 1)
    )
    if repeated.height:
        first = repeated.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: period {first['period']} has "
            f"{first['len']} {first['sub_type']} markers"
        )

    def side(sub_type: str, prefix: str) -> pl.DataFrame:
        return markers.filter(pl.col("sub_type") == sub_type).select(
            "game_id",
            "period",
            pl.col("wall_clock").alias(f"{prefix}_wall"),
            pl.col("action_number").alias(f"{prefix}_action_number"),
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
        period_length().alias("length"),
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
    # The clock only stops, so a period takes at least its own length on
    # the wall; one that takes hours has stamps from another day
    wall_length = pl.col("end_wall") - pl.col("start_wall")
    short = periods.filter(wall_length < pl.col("length"))
    if short.height:
        first = short.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: period {first['period']} takes "
            f"{first['end_wall'] - first['start_wall']} s of wall clock for "
            f"{first['length']} s of play"
        )
    long = periods.filter(wall_length > MAX_PERIOD_WALL_SECONDS)
    if long.height:
        first = long.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: period {first['period']} takes "
            f"{(first['end_wall'] - first['start_wall']) / 60:.0f} minutes of wall clock"
        )

    return (
        periods.with_columns(
            (pl.col("length").cum_sum().over("game_id") - pl.col("length")).alias(
                "start_seconds"
            )
        )
        .with_columns((pl.col("start_seconds") + pl.col("length")).alias("end_seconds"))
        .select("game_id", *PERIOD_COLUMNS)
    )


def place_plays(plays: pl.DataFrame, periods: pl.DataFrame) -> pl.DataFrame:
    """
    Put plays on the game clock: seconds since tip-off from the period and the clock.

    Args:
        plays: Play-by-play rows with ``game_id``, ``period`` and ``clock``.
        periods: The game clock from build_periods, ``game_id`` included.

    Returns:
        The plays with ``game_seconds`` added, in the input's row order.

    Raises:
        RecapError: If a clock string does not parse, or a play's period
            has no markers.
    """
    placed = plays.with_row_index("_order").join(
        periods.select("game_id", "period", "end_seconds"),
        on=["game_id", "period"],
        how="left",
    )
    unplaced = placed.filter(pl.col("end_seconds").is_null())
    if unplaced.height:
        first = unplaced.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: period {first['period']} has no markers "
            f"(action {first['action_number']})"
        )
    placed = placed.with_columns(
        parse_clock_seconds(pl.col("clock")).alias("_remaining")
    )
    unparsed = placed.filter(pl.col("_remaining").is_null())
    if unparsed.height:
        first = unparsed.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: clock {first['clock']!r} does not parse "
            f"(action {first['action_number']})"
        )
    game_seconds = (
        (pl.col("end_seconds") - pl.col("_remaining")).round(0).cast(pl.Int64)
    )
    return (
        placed.with_columns(game_seconds.alias("game_seconds"))
        .sort("_order")
        .drop("_order", "_remaining", "end_seconds")
    )


def game_clock(pbp: pl.DataFrame, periods: pl.DataFrame) -> pl.DataFrame:
    """
    The mapping from wall clock to game seconds: every row of the game, on both.

    One row per wall-clock second the feed stamped (the last row on
    that second, in feed order), game seconds monotone so the mapping
    never runs backwards.

    Args:
        pbp: Play-by-play rows after stamp_wall_clock, one or more games.
        periods: The game clock from build_periods, ``game_id`` included.

    Returns:
        ``game_id``, ``wall_clock``, ``game_seconds``, sorted by game
        and wall clock.
    """
    return (
        place_plays(pbp.filter(pl.col("action_type") != GAME_ACTION_TYPE), periods)
        .with_columns(pl.col("game_seconds").cum_max().over("game_id"))
        .select("game_id", "wall_clock", "game_seconds")
        .unique(subset=["game_id", "wall_clock"], keep="last", maintain_order=True)
        .sort("game_id", "wall_clock")
    )


def align_comments(
    comments: pl.DataFrame, periods: pl.DataFrame, clock: pl.DataFrame
) -> pl.DataFrame:
    """
    Place comments on the game clock of their game.

    A comment posted inside a period maps by interpolation between the
    two feed rows either side of it on wall clock: flat between two rows
    on one game second, as a timeout and the substitutions at its end
    are; one posted in a break pins to the end of
    the period just played; before tip-off it is ``pre`` at second 0,
    after the last buzzer ``post`` at the game's last second.

    Args:
        comments: Rows with ``game_id`` and ``created_utc``; any other
            columns ride along.
        periods: The game clock from build_periods, ``game_id`` included.
        clock: The mapping from game_clock for the same games.

    Returns:
        The comments with ``game_seconds``, ``phase`` and ``period``
        (null outside live and break) added, in the input's row order.
        A comment whose game has no clock in ``periods`` reads as
        ``pre``; callers pass the games they aligned.
    """
    bound_columns = ["game_id", "period", "end_seconds"]
    ordered = periods.sort("game_id", "period").with_columns(
        pl.col("start_wall").shift(-1).over("game_id").alias("_next_start_wall")
    )
    bounds = pl.concat(
        [
            ordered.select(
                *bound_columns,
                pl.col("start_wall").alias("bound"),
                pl.lit(PHASE_LIVE).alias("phase"),
            ),
            # The end marker's own second is still live; a break exists
            # only if the next period starts later than the second after
            ordered.filter(
                pl.col("_next_start_wall").is_null()
                | (pl.col("_next_start_wall") > pl.col("end_wall") + 1)
            ).select(
                *bound_columns,
                (pl.col("end_wall") + 1).alias("bound"),
                pl.lit(PHASE_BREAK).alias("phase"),
            ),
        ]
    ).sort("game_id", "bound")
    finals = periods.group_by("game_id").agg(
        pl.col("period").max().alias("last_period"),
        pl.col("end_seconds").max().alias("total_seconds"),
    )
    neighbours = clock.sort("game_id", "wall_clock").select(
        "game_id",
        pl.col("wall_clock").alias("_wall"),
        pl.col("game_seconds").alias("_seconds"),
        pl.col("wall_clock").shift(-1).over("game_id").alias("_next_wall"),
        pl.col("game_seconds").shift(-1).over("game_id").alias("_next_seconds"),
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
        .join_asof(
            neighbours,
            left_on="created_utc",
            right_on="_wall",
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
    fraction = (pl.col("created_utc") - pl.col("_wall")) / (
        pl.col("_next_wall") - pl.col("_wall")
    )
    live_seconds = (
        pl.when(
            pl.col("_next_wall").is_null() | (pl.col("_next_wall") == pl.col("_wall"))
        )
        .then(pl.col("_seconds"))
        .otherwise(
            pl.col("_seconds")
            + (fraction * (pl.col("_next_seconds") - pl.col("_seconds"))).round(0)
        )
    )
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


# --- Plays and stints -------------------------------------------------------


def derive_kind(pbp: pl.DataFrame, player_id: int) -> pl.DataFrame:
    """
    Name each play's kind and flag the focus player's plays.

    The kind is the feed's action type under the recap's vocabulary; a
    substitution is ``sub_in`` or ``sub_out`` by its sub type, and each
    row names its own player. His assists sit on a teammate's made shot
    and are his plays too.

    Args:
        pbp: One game's play-by-play.
        player_id: The focus player's id.

    Returns:
        The rows with ``kind`` and ``is_focus`` added.
    """
    kind = (
        pl.when(pl.col("action_type") == PERIOD_ACTION_TYPE)
        .then(
            pl.when(pl.col("sub_type") == PERIOD_START)
            .then(pl.lit(KIND_PERIOD_START))
            .otherwise(pl.lit(KIND_PERIOD_END))
        )
        .when(pl.col("action_type") == SUBSTITUTION_ACTION_TYPE)
        .then(
            pl.when(pl.col("sub_type") == SUB_IN_SUB_TYPE)
            .then(pl.lit(KIND_SUB_IN))
            .otherwise(pl.lit(KIND_SUB_OUT))
        )
        .otherwise(
            pl.col("action_type").replace_strict(
                ACTION_TYPE_KINDS, default=KIND_OTHER, return_dtype=pl.String
            )
        )
    )
    is_focus = (pl.col("person_id") == player_id) | (
        pl.col("assist_person_id") == player_id
    ).fill_null(False)
    return pbp.with_columns(kind.alias("kind"), is_focus.alias("is_focus"))


def pair_plays(pbp: pl.DataFrame) -> pl.DataFrame:
    """
    Point each block and steal at the play it ended.

    A block follows the shot it ended and a steal the turnover, each
    on its own action number; the play before names the ender in its
    own field. A block borrows the shot's location, so it draws where
    the shot was taken.

    Args:
        pbp: One game's play-by-play with ``kind`` (derive_kind), in
            feed order.

    Returns:
        The rows with ``paired_action_number`` added (null off a block
        or steal), blocks carrying their shot's position.

    Raises:
        RecapError: If a block or steal does not follow the play it ended.
    """
    previous = {
        name: pl.col(name).shift(1).over("game_id").alias(f"_prev_{name}")
        for name in ("action_number", *_SHOT_LOCATION, *_ENDER_FIELDS.values())
    }
    ender = pl.col("kind").is_in(list(_ENDER_FIELDS))
    named_before = pl.when(False).then(False)
    for kind, field_name in _ENDER_FIELDS.items():
        named_before = named_before.when(pl.col("kind") == kind).then(
            pl.col(f"_prev_{field_name}") == pl.col("person_id")
        )
    paired = pbp.with_columns(*previous.values()).with_columns(
        (ender & named_before.fill_null(False)).alias("_paired")
    )
    unpaired = paired.filter(ender & ~pl.col("_paired"))
    if unpaired.height:
        first = unpaired.row(0, named=True)
        raise RecapError(
            f"{first['game_id']}: {first['kind']} at action "
            f"{first['action_number']} does not follow the play it ended"
        )
    borrows = pl.col("kind") == KIND_BLOCK
    return paired.with_columns(
        pl.when(pl.col("_paired"))
        .then(pl.col("_prev_action_number"))
        .alias("paired_action_number"),
        *(
            pl.when(borrows)
            .then(pl.col(f"_prev_{name}"))
            .otherwise(pl.col(name))
            .alias(name)
            for name in _SHOT_LOCATION
        ),
    ).drop("_paired", *(f"_prev_{name}" for name in previous))


def build_plays(
    pbp: pl.DataFrame, periods: pl.DataFrame, player_id: int
) -> pl.DataFrame:
    """
    The plays a recap ships, on both clocks, in RECAP_PLAYS_SCHEMA's shape.

    Every row of the feed but its closing one, which is not a play:
    both teams' actions, the substitutions, the period markers and the
    timeouts. The page counts every player's line from these rows.

    Args:
        pbp: One game's play-by-play after stamp_wall_clock.
        periods: The game's clock (build_periods), ``game_id`` included.
        player_id: The focus player's id.

    Returns:
        The plays in feed order, columns as RECAP_PLAYS_SCHEMA plus
        ``game_id`` in front.

    Raises:
        RecapError: If the focus player has no action in the game, or
            from pair_plays and place_plays.
    """
    prepared = pair_plays(
        derive_kind(pbp.filter(pl.col("action_type") != GAME_ACTION_TYPE), player_id)
    )
    if not prepared["is_focus"].any():
        game_id = pbp["game_id"][0] if pbp.height else "?"
        raise RecapError(f"{game_id}: player {player_id} has no action")
    made = (
        pl.when(pl.col("shot_result") == "Made")
        .then(True)
        .when(pl.col("shot_result") == "Missed")
        .then(False)
        .when(pl.col("kind") == KIND_HEAVE)
        .then(False)
        .otherwise(None)
        .cast(pl.Boolean)
    )
    return (
        place_plays(prepared, periods)
        .with_columns(
            made.alias("made"),
            pl.col("action_type")
            .replace_strict(SHOT_VALUES, default=0, return_dtype=pl.Int64)
            .alias("shot_value"),
            pl.col("score_home").cast(pl.Int64),
            pl.col("score_away").cast(pl.Int64),
        )
        .select("game_id", *RECAP_PLAYS_SCHEMA.names())
    )


def _player_stints(
    events: Sequence[tuple[int, str, int, bool]],
    bounds: Sequence[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    """
    One player's on-court intervals from his rows.

    Args:
        events: His rows in feed order: period, kind, game seconds, and
            whether the row is a play made on the floor.
        bounds: Each period with its start and end in game seconds.

    Returns:
        (period, start_seconds, end_seconds) in game order.
    """
    stints: list[tuple[int, int, int]] = []
    on_court: bool | None = None
    for period, start, end in bounds:
        own = [event for event in events if event[0] == period]
        subs = [(kind, seconds) for _, kind, seconds, _ in own if kind in SUB_KINDS]
        if on_court is None:
            on_court = (
                subs[0][0] == KIND_SUB_OUT
                if subs
                else any(on_floor for *_, on_floor in own)
            )
        opened = start if on_court else None
        for kind, seconds in subs:
            if kind == KIND_SUB_OUT:
                since = start if opened is None else opened
                if seconds > since:
                    stints.append((period, since, seconds))
                opened = None
            elif opened is None:
                opened = seconds
        if opened is not None:
            stints.append((period, opened, end))
        on_court = opened is not None
    return stints


def build_stints(plays: pl.DataFrame, periods: pl.DataFrame) -> pl.DataFrame:
    """
    Every player's on-court intervals, in game seconds.

    The feed never logs the opening five, so the first period's opening
    state is inferred per player: on the floor if his first substitution
    in it takes him off, off if it brings him on, and with no
    substitution at all, on if he made any play, an assist included. A
    technical foul or an ejection is not one: either can be called on
    the bench. From there the substitutions open and close intervals;
    the state carries across each break, where the feed logs the lineup
    changes as substitutions at the period's first second; an interval
    open at the buzzer closes on it. A check-out while he reads as off
    proves he was on since the period started.

    Args:
        plays: The recap's plays (build_plays), in feed order.
        periods: The game's clock (build_periods).

    Returns:
        RECAP_STINTS_SCHEMA rows in game order: by when the interval
        opens, then by player. A player with no interval has no row.
    """
    called_on_bench = (
        (pl.col("action_type") == FOUL_ACTION_TYPE)
        & (pl.col("sub_type") == TECHNICAL_SUB_TYPE)
    ) | (pl.col("kind") == KIND_EJECTION)
    feed = plays.with_row_index("_order")
    columns = ["_order", "team_tricode", "period", "kind", "game_seconds"]
    events = pl.concat(
        [
            feed.filter(pl.col("person_id") > 0).select(
                "person_id", *columns, (~called_on_bench).alias("on_floor")
            ),
            feed.filter(pl.col("assist_person_id").is_not_null()).select(
                pl.col("assist_person_id").alias("person_id"),
                *columns,
                pl.lit(True).alias("on_floor"),
            ),
        ]
    ).sort("_order")
    by_player: dict[int, list[tuple[int, str, int, bool]]] = {}
    teams: dict[int, str] = {}
    for person_id, _, tricode, period, kind, seconds, on_floor in events.rows():
        by_player.setdefault(person_id, []).append((period, kind, seconds, on_floor))
        teams.setdefault(person_id, tricode)
    bounds = (
        periods.sort("period").select("period", "start_seconds", "end_seconds").rows()
    )
    rows = [
        (person_id, teams[person_id], *stint)
        for person_id, own in by_player.items()
        for stint in _player_stints(own, bounds)
    ]
    return pl.DataFrame(rows, schema=RECAP_STINTS_SCHEMA, orient="row").sort(
        "start_seconds", "person_id"
    )


def stint_minutes(stints: pl.DataFrame) -> pl.DataFrame:
    """
    Each player's minutes on the floor, rounded half up as the box score rounds.

    Args:
        stints: The stints frame (build_stints).

    Returns:
        STINT_MINUTES_SCHEMA rows, one per player, in the frame's order.
    """
    seconds = (pl.col("end_seconds") - pl.col("start_seconds")).sum()
    return (
        stints.group_by("person_id", "team_tricode", maintain_order=True)
        .agg(((seconds + 30) // 60).alias("minutes"))
        .select(STINT_MINUTES_SCHEMA.names())
    )


def floor_gaps(stints: pl.DataFrame, periods: pl.DataFrame) -> pl.DataFrame:
    """
    The spans where the stints do not put five players per team on the floor.

    Args:
        stints: The stints frame (build_stints).
        periods: The game's clock (build_periods).

    Returns:
        FLOOR_GAP_SCHEMA rows: the team, the span in game seconds and how
        many read as on the floor through it. Empty when every team has
        five from tip-off to the last buzzer.
    """
    teams = stints.select("team_tricode").unique()
    total = periods["end_seconds"].max()

    def steps(frame: pl.DataFrame, at: pl.Expr, step: int) -> pl.DataFrame:
        return frame.select(
            "team_tricode",
            at.cast(pl.Int64).alias("at"),
            pl.lit(step, dtype=pl.Int64).alias("step"),
        )

    spans = (
        pl.concat(
            [
                steps(stints, pl.col("start_seconds"), 1),
                steps(stints, pl.col("end_seconds"), -1),
                steps(teams, pl.lit(0), 0),
                steps(teams, pl.lit(total), 0),
            ]
        )
        .group_by("team_tricode", "at")
        .agg(pl.col("step").sum())
        .sort("team_tricode", "at")
        .with_columns(
            pl.col("step").cum_sum().over("team_tricode").alias("on_floor"),
            pl.col("at").shift(-1).over("team_tricode").alias("until"),
        )
        .filter(pl.col("until").is_not_null())
    )
    # Neighbouring spans with one count are one gap, however many
    # substitutions happen under it
    changed = pl.col("on_floor") != pl.col("on_floor").shift(1).over("team_tricode")
    return (
        spans.with_columns(
            changed.fill_null(True)
            .cast(pl.Int64)
            .cum_sum()
            .over("team_tricode")
            .alias("_run")
        )
        .group_by("team_tricode", "_run", maintain_order=True)
        .agg(
            pl.col("at").first().alias("start_seconds"),
            pl.col("until").last().alias("end_seconds"),
            pl.col("on_floor").first(),
        )
        .filter(pl.col("on_floor") != FLOOR_SIZE)
        .select(FLOOR_GAP_SCHEMA.names())
        .sort("start_seconds", "team_tricode")
    )


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


# --- The room's reaction lag, season-wide ------------------------------------


def read_game_clock(
    game_id: str, pbp_dir: Path
) -> tuple[pl.DataFrame, pl.DataFrame] | None:
    """
    One banked game's play-by-play, stamped, and the clock its markers build.

    Args:
        game_id: The game.
        pbp_dir: The season's play-by-play directory.

    Returns:
        ``(pbp, periods)``, or None when the feed is not banked or its
        markers do not build a clock (logged).
    """
    path = play_by_play_path(pbp_dir, game_id)
    if not path.exists():
        return None
    try:
        pbp = stamp_wall_clock(pl.read_parquet(path))
        return pbp, build_periods(pbp)
    except RecapError as e:
        logger.warning(f"no clock for {game_id}, skipped: {e}")
        return None


def anchor_candidates(
    pbp: pl.DataFrame, periods: pl.DataFrame, players: pl.DataFrame
) -> pl.DataFrame:
    """
    A game's anchor candidates: every tracked player's blocks, steals and made dunks.

    Args:
        pbp: One game's play-by-play after stamp_wall_clock.
        periods: The game's clock (build_periods).
        players: The Player dimension (attributed_player, player_id).

    Returns:
        ANCHOR_CANDIDATE_SCHEMA rows: each play on both clocks, its player
        as the fact names him, and the third of its period it fell in.
    """
    kind = (
        pl.when(pl.col("action_type") == "block")
        .then(pl.lit(KIND_BLOCK))
        .when(pl.col("action_type") == "steal")
        .then(pl.lit(KIND_STEAL))
        .when(
            (pl.col("action_type") == "2pt")
            & (pl.col("sub_type") == DUNK_SUB_TYPE)
            & (pl.col("shot_result") == "Made")
        )
        .then(pl.lit(KIND_DUNK))
    )
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
    the play's own wall clock.

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
        .sort("_gap", "action_number")
        .unique(subset=burst_key, keep="first", maintain_order=True)
        .sort(["reaction_n", "minute"], descending=[True, False])
        .unique(subset=["game_id", "action_number"], keep="first", maintain_order=True)
        .select("game_id", "action_number", "reaction_n", "first_reaction_utc")
    )
    accepted = pl.col("reaction_n") >= RECAP_ANCHOR_MIN_REACTIONS
    return (
        candidates.join(best, on=["game_id", "action_number"], how="left")
        .with_columns(pl.col("reaction_n").fill_null(0))
        .with_columns(
            accepted.alias("accepted"),
            pl.when(accepted)
            .then(pl.col("first_reaction_utc") - pl.col("wall_clock"))
            .alias("offset_seconds"),
        )
        .sort("game_id", "action_number")
    )


def reaction_lag_figures(anchors: pl.DataFrame) -> ReactionLag:
    """
    Summarize matched candidates as the published reaction-lag figures.

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


def unmeasured_reaction_lag() -> ReactionLag:
    """The figures of a season that curates no recap: nothing measured."""
    return {
        "candidates": 0,
        "anchors": 0,
        "games": 0,
        "median_offset_seconds": None,
        "p25_offset_seconds": None,
        "p75_offset_seconds": None,
    }


def measure_reaction_lag(
    fact: pl.DataFrame,
    posts: pl.DataFrame,
    players: pl.DataFrame,
    pbp_dir: Path,
) -> tuple[pl.DataFrame, ReactionLag]:
    """
    Measure how long the room takes to react to a play, over every threaded game.

    The clock is the feed's own, so what the anchors measure is the
    room's lag, once, season-wide: a single game rarely draws enough
    named reactions to measure its own. Nothing is moved by it.

    Args:
        fact: The usable fact rows, at least those in game threads.
        posts: The Post bridge.
        players: The Player dimension (attributed_player, player_id).
        pbp_dir: The season's play-by-play directory.

    Returns:
        Every candidate matched (match_anchors) and the figures
        (reaction_lag_figures). The median offset per third of the
        period is logged.
    """
    threads = posts.filter(
        (pl.col("post_type") == GAME_THREAD) & pl.col("game_id").is_not_null()
    ).select("post_id", "game_id")
    frames = [ANCHOR_CANDIDATE_SCHEMA.to_frame()]
    skipped = 0
    for game_id in sorted(threads["game_id"].unique().to_list()):
        banked = read_game_clock(game_id, pbp_dir)
        if banked is None:
            skipped += 1
            continue
        frames.append(anchor_candidates(*banked, players))
    anchors = match_anchors(pl.concat(frames), named_reactions(fact, threads))
    figures = reaction_lag_figures(anchors)

    by_third = (
        anchors.filter(pl.col("accepted"))
        .group_by("third")
        .agg(pl.col("offset_seconds").median().round(0).cast(pl.Int64))
        .sort("third")
        .rows()
    )
    logger.info(
        f"Reaction lag: {figures['anchors']:,} anchors of {figures['candidates']:,} "
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


def build_recap(
    spec: ResolvedSpec,
    *,
    fact: pl.DataFrame,
    posts: pl.DataFrame,
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
        player_games: The box-score lines (game_id, attributed_player,
            minutes).
        players: The Player dimension (attributed_player, player_id).
        pbp: The game's play-by-play (load_live_play_by_play).
        stamps: The build's lineage for the header.

    Returns:
        The document, every frame validated against its schema.

    Raises:
        RecapError: From the clock and the plays, or if the focus
            player has no box-score line in the game.
    """
    pbp = stamp_wall_clock(pbp)
    periods = build_periods(pbp)
    plays = build_plays(pbp, periods, spec.player_id)
    stints = build_stints(plays, periods)
    for team, start, end, on_floor in floor_gaps(stints, periods).rows():
        logger.warning(
            f"recap {spec.key}: {team} reads {on_floor} on the floor "
            f"from {start} to {end} s"
        )

    aligned = align_comments(
        fact.filter(pl.col("link_id").is_in(list(spec.thread_ids))).with_columns(
            pl.lit(spec.game_id).alias("game_id")
        ),
        periods,
        game_clock(pbp, periods),
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
    minutes = stint_minutes(stints).filter(pl.col("person_id") == spec.player_id)
    focus_minutes = int(minutes["minutes"][0]) if minutes.height else 0
    minutes_diff = focus_minutes - box_minutes
    if minutes_diff:
        # The first period's inferred opening state is where stints go
        # wrong: a period played with no substitution and no play reads
        # as bench
        logger.warning(
            f"recap {spec.key}: {focus_minutes} stint minutes against "
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
    the size of the swing, as the input to curation. The clock is the
    recaps' own, so the scan and a recap can never disagree.

    Args:
        fact: The usable fact rows, at least those in game threads.
        posts: The Post bridge.
        games: The Game dimension (game_id, home_team, away_team).
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
    periods: list[pl.DataFrame] = []
    clocks: list[pl.DataFrame] = []
    skipped: list[str] = []
    for game_id in sorted(threads["game_id"].unique().to_list()):
        banked = read_game_clock(game_id, pbp_dir)
        if banked is None:
            skipped.append(game_id)
            continue
        periods.append(banked[1])
        clocks.append(game_clock(*banked))
    if not periods:
        return pl.DataFrame(), skipped
    clock = pl.concat(periods)

    aligned = align_comments(
        fact.filter(pl.col("attributed_player").is_not_null())
        .join(threads, left_on="link_id", right_on="post_id", how="inner")
        .filter(pl.col("game_id").is_in(clock["game_id"].unique().to_list())),
        clock,
        pl.concat(clocks),
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
