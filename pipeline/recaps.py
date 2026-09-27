"""
Recaps: a game's live thread replayed against its play-by-play.

A recap places one game's plays and one player's comments on a shared
clock. The archive's period markers carry Eastern wall-clock time to the
minute ("Start of 1st Period (8:17 PM EST)"), so the game clock maps to
wall-clock time by a straight line inside each period, and a comment's
wall-clock timestamp maps back to game seconds through the same line.
Comments posted during a break pin to the break; comments before tip-off
and after the buzzer keep their phase. The mapping is a derivation with
an error, measured (never corrected) by the reactions to the focus
player's blocks, steals and dunks.

Every function here is a frame transform; the archive and the fact are
read at the edges by the aggregation stage.
"""

import polars as pl

from pipeline.posts import POST_LOCAL_TZ

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
