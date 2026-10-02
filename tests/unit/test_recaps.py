"""
Tests for pipeline/recaps.py: the shared clock and what sits on it.

Frames are built locally: a feed row in LIVE_PLAY_BY_PLAY_SCHEMA's shape
with its own timestamp, period markers stamped like the feed stamps
them, and a comment row with the columns the clock needs. Wall-clock
expectations are derived from the timestamps in the test, never from
the code under test.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from pipeline.recaps import (
    PERIOD_COLUMNS,
    RecapError,
    RecapStamps,
    ResolvedSpec,
    align_comments,
    box_lines,
    build_periods,
    build_plays,
    build_recap,
    build_stints,
    check_box,
    derive_kind,
    floor_gaps,
    game_clock,
    measure_reaction_lag,
    minutes_off,
    pair_plays,
    parse_clock_seconds,
    period_counts,
    place_plays,
    reaction_lag_figures,
    resolve_recap_specs,
    scan_candidates,
    select_comments,
    serialize_recap,
    stamp_wall_clock,
    stint_seconds,
    swing,
    write_recap,
    write_recaps,
)
from pipeline.schemas import (
    LIVE_PLAY_BY_PLAY_SCHEMA,
    RECAP_COMMENTS_SCHEMA,
    RECAP_FRAME_SCHEMAS,
    RECAP_NULLABLE_COLUMNS,
    RECAP_PLAYS_SCHEMA,
    RECAP_STINTS_SCHEMA,
    SCHEMA_VERSION,
    validate_nullability,
    validate_schema,
)
from tests.conftest import live_action
from utils.recaps_config import RecapSpec

GAME = "0042500317"
OTHER = "0022500001"
UTC = ZoneInfo("UTC")
# The G7 fixture plays on the night of 2026-06-01 Eastern, 2026-06-02 UTC
DAY = date(2026, 6, 2)


def _stamp(hour: int, minute: int, second: int = 0, day: date = DAY) -> str:
    """A feed timestamp: UTC, to a tenth."""
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}:{second:02d}.0Z"


def _epoch(hour: int, minute: int, second: int = 0, day: date = DAY) -> int:
    """Epoch seconds of a UTC time."""
    return int(
        datetime(
            day.year, day.month, day.day, hour, minute, second, tzinfo=UTC
        ).timestamp()
    )


def _action(action_number: int = 1, **overrides) -> dict:
    """One feed row; feed order follows the action number unless overridden."""
    return live_action(
        game_id=overrides.pop("game_id", GAME),
        action_number=action_number,
        order_number=overrides.pop("order_number", action_number),
        **overrides,
    )


def _pbp(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=LIVE_PLAY_BY_PLAY_SCHEMA)


def _marker(period: int, sub_type: str, stamp: str, action_number: int, **over) -> dict:
    """A period marker as the feed logs it: 'Period Start' with a timestamp."""
    return _action(
        action_number,
        period=period,
        action_type="period",
        sub_type=sub_type,
        description=f"Period {sub_type.title()}",
        time_actual=stamp,
        clock="PT12M00.00S" if sub_type == "start" else "PT00M00.00S",
        **over,
    )


# WCF G7's eight markers, stamped as the feed stamps them
G7_MARKERS = [
    _marker(1, "start", _stamp(0, 17), 1),
    _marker(1, "end", _stamp(0, 46), 121),
    _marker(2, "start", _stamp(0, 49), 122),
    _marker(2, "end", _stamp(1, 19), 250),
    _marker(3, "start", _stamp(1, 36), 251),
    _marker(3, "end", _stamp(2, 13), 392),
    _marker(4, "start", _stamp(2, 17), 393),
    _marker(4, "end", _stamp(2, 49), 507),
]


@pytest.fixture
def g7_periods() -> pl.DataFrame:
    """The G7 clock from its markers."""
    return build_periods(stamp_wall_clock(_pbp(G7_MARKERS)))


class TestParseClock:
    """The feed's ISO-style clock to seconds remaining."""

    @pytest.mark.parametrize(
        "clock,expected",
        [
            ("PT12M00.00S", 720.0),
            ("PT11M21.00S", 681.0),
            ("PT00M40.20S", 40.2),
            ("PT00M00.00S", 0.0),
        ],
    )
    def test_seconds_remaining(self, clock, expected):
        """Minutes and fractional seconds add up."""
        frame = pl.DataFrame({"clock": [clock]}).select(
            parse_clock_seconds(pl.col("clock")).alias("s")
        )
        assert frame["s"][0] == pytest.approx(expected)

    def test_malformed_is_null(self):
        """Anything else is null for the caller to refuse."""
        frame = pl.DataFrame({"clock": ["12:00", ""]}).select(
            parse_clock_seconds(pl.col("clock")).alias("s")
        )
        assert frame["s"].to_list() == [None, None]


class TestStampWallClock:
    """Every row's wall clock is its own timestamp, in feed order."""

    def test_timestamp_to_the_second(self):
        """The feed's tenths are dropped; the second is the row's wall clock."""
        stamped = stamp_wall_clock(
            _pbp([_action(5, time_actual="2026-06-02T00:23:08.7Z")])
        )

        assert stamped["wall_clock"][0] == _epoch(0, 23, 8)
        assert stamped["wall_clock"].dtype == pl.Int64

    def test_a_row_stamped_earlier_than_its_predecessor_takes_its_second(self):
        """Order is the feed's: a stamp that runs backwards is held at the
        row before, and the rows after it read their own stamps again."""
        rows = [
            _action(1, time_actual=_stamp(0, 20, 0)),
            _action(2, time_actual=_stamp(0, 20, 30)),
            _action(3, time_actual=_stamp(0, 20, 10)),
            _action(4, time_actual=_stamp(0, 20, 40)),
        ]

        stamped = stamp_wall_clock(_pbp(rows))

        assert stamped["wall_clock"].to_list() == [
            _epoch(0, 20, 0),
            _epoch(0, 20, 30),
            _epoch(0, 20, 30),
            _epoch(0, 20, 40),
        ]

    def test_rows_are_put_in_feed_order(self):
        """Whatever order the rows arrive in, order_number decides."""
        rows = [
            _action(2, order_number=20, time_actual=_stamp(0, 21)),
            _action(1, order_number=10, time_actual=_stamp(0, 20)),
        ]

        stamped = stamp_wall_clock(_pbp(rows))

        assert stamped["action_number"].to_list() == [1, 2]

    def test_games_are_stamped_apart(self):
        """One game's late stamp never holds another game's rows."""
        rows = [
            _action(1, time_actual=_stamp(3, 0)),
            _action(1, game_id=OTHER, time_actual=_stamp(0, 5)),
        ]

        stamped = stamp_wall_clock(_pbp(rows))

        assert stamped.filter(pl.col("game_id") == OTHER)["wall_clock"][0] == _epoch(
            0, 5
        )

    def test_unparsable_timestamp_raises(self):
        """A stamp the feed's format does not cover names its action."""
        with pytest.raises(
            RecapError, match="'yesterday' does not parse \\(action 7\\)"
        ):
            stamp_wall_clock(_pbp([_action(7, time_actual="yesterday")]))


class TestBuildPeriods:
    """The game clock from the period markers' timestamps."""

    def test_columns_and_order(self, g7_periods):
        """game_id, then the period columns, one row per period in order."""
        assert g7_periods.columns == ["game_id", *PERIOD_COLUMNS]
        assert g7_periods["period"].to_list() == [1, 2, 3, 4]
        assert g7_periods["start_seconds"].to_list() == [0, 720, 1440, 2160]
        assert g7_periods["end_seconds"].to_list() == [720, 1440, 2160, 2880]
        assert g7_periods["start_action_number"].to_list() == [1, 122, 251, 393]
        assert g7_periods["end_action_number"].to_list() == [121, 250, 392, 507]

    def test_wall_bounds_are_the_markers_timestamps(self, g7_periods):
        """Each bound is its marker's own stamp, to the second."""
        assert g7_periods["start_wall"][0] == _epoch(0, 17)
        assert g7_periods["end_wall"][3] == _epoch(2, 49)

    def test_overtime_periods_are_five_minutes(self):
        """Period 5 adds 300 seconds after regulation's 2,880."""
        markers = [
            *G7_MARKERS,
            _marker(5, "start", _stamp(2, 52), 508),
            _marker(5, "end", _stamp(3, 5), 560),
        ]

        periods = build_periods(stamp_wall_clock(_pbp(markers)))

        assert periods["start_seconds"][4] == 2880
        assert periods["end_seconds"][4] == 3180

    def test_vectorized_over_two_games(self):
        """Two games' markers in one frame give two clocks."""
        other = [
            _marker(
                1, "start", _stamp(23, 10, day=date(2026, 1, 15)), 1, game_id=OTHER
            ),
            _marker(1, "end", _stamp(23, 40, day=date(2026, 1, 15)), 60, game_id=OTHER),
        ]

        periods = build_periods(stamp_wall_clock(_pbp([*G7_MARKERS, *other])))

        assert periods["game_id"].to_list() == [OTHER] + [GAME] * 4
        assert periods.filter(pl.col("game_id") == OTHER)["start_wall"][0] == _epoch(
            23, 10, day=date(2026, 1, 15)
        )

    def test_missing_end_marker_raises(self):
        """A period with a start and no end names the game and the period."""
        markers = [
            m for m in G7_MARKERS if not (m["period"] == 2 and m["sub_type"] == "end")
        ]

        with pytest.raises(RecapError, match=f"{GAME}: period 2 has no end marker"):
            build_periods(stamp_wall_clock(_pbp(markers)))

    def test_repeated_start_marker_raises(self):
        """Two starts for one period is a feed defect, not a choice."""
        markers = [*G7_MARKERS, _marker(3, "start", _stamp(1, 37), 252)]

        with pytest.raises(RecapError, match="period 3 has 2 start markers"):
            build_periods(stamp_wall_clock(_pbp(markers)))

    def test_period_ending_before_it_starts_raises(self):
        """A period whose end precedes its start has no clock to read."""
        markers = [*G7_MARKERS]
        markers[3] = _marker(2, "end", _stamp(0, 40), 250)

        with pytest.raises(RecapError, match="period 2 ends at or before it starts"):
            build_periods(stamp_wall_clock(_pbp(markers)))

    def test_non_contiguous_periods_raise(self):
        """Periods 1, 2, 4 with no 3: the clock cannot accumulate."""
        markers = [m for m in G7_MARKERS if m["period"] != 3]

        with pytest.raises(RecapError, match="not contiguous"):
            build_periods(stamp_wall_clock(_pbp(markers)))

    def test_overlapping_periods_raise(self):
        """A period whose start marker is logged, and stamped, before the
        previous period's end."""
        markers = [*G7_MARKERS]
        markers[4] = _marker(3, "start", _stamp(1, 15), 251, order_number=249)

        with pytest.raises(RecapError, match="period 3 starts before period 2 ends"):
            build_periods(stamp_wall_clock(_pbp(markers)))

    def test_period_shorter_than_its_play_raises(self):
        """The clock only stops, so eleven wall minutes cannot hold twelve
        of play: the stamps are wrong."""
        markers = [*G7_MARKERS]
        markers[1] = _marker(1, "end", _stamp(0, 28), 121)

        with pytest.raises(
            RecapError, match="period 1 takes 660 s of wall clock for 720 s of play"
        ):
            build_periods(stamp_wall_clock(_pbp(markers)))

    def test_period_longer_than_the_bound_raises(self):
        """A period stamped hours long has stamps from another day."""
        markers = [G7_MARKERS[0], _marker(1, "end", _stamp(1, 50), 121)]

        with pytest.raises(RecapError, match="period 1 takes 93 minutes of wall clock"):
            build_periods(stamp_wall_clock(_pbp(markers)))


def _comments(*created: int, game_id: str = GAME) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "comment_id": [f"c{i}" for i in range(len(created))],
            "game_id": [game_id] * len(created),
            "created_utc": list(created),
        },
        schema={"comment_id": pl.String, "game_id": pl.String, "created_utc": pl.Int64},
    )


# --- Plays and stints -------------------------------------------------------

OKC, SAS = 1610612760, 1610612759
CHET, WALLACE, HARTENSTEIN, MCCAIN = 1631096, 1641717, 1628392, 1642275
WEMBY, HARPER, CASTLE, VASSELL = 1641705, 1642844, 1642264, 1627936


def _okc(action_number: int, **over) -> dict:
    return _action(action_number, team_id=OKC, team_tricode="OKC", **over)


def _sas(action_number: int, **over) -> dict:
    return _action(action_number, team_id=SAS, team_tricode="SAS", **over)


def _chet(action_number: int, **over) -> dict:
    return _okc(
        action_number,
        person_id=CHET,
        player_name="Holmgren",
        player_name_i="C. Holmgren",
        **over,
    )


def _sub(
    factory, action_number: int, sub_type: str, clock: str, stamp: str, **over
) -> dict:
    return factory(
        action_number,
        action_type="substitution",
        sub_type=sub_type,
        clock=clock,
        time_actual=stamp,
        **over,
    )


# A G7-shaped game: the eight markers plus the plays the rules turn on.
G7_PLAYS = [
    G7_MARKERS[0],
    _chet(
        2,
        action_type="jumpball",
        sub_type="recovered",
        time_actual=_stamp(0, 17, 4),
        description="Jump Ball C. Holmgren vs. V. Wembanyama: Tip to S. Castle",
    ),
    _chet(
        8,
        clock="PT10M41.00S",
        time_actual=_stamp(0, 18, 40),
        action_type="2pt",
        sub_type="Jump Shot",
        shot_result="Made",
        is_field_goal=1,
        x=18.4,
        y=62.1,
        x_legacy=118,
        y_legacy=0,
        shot_distance=12.3,
        points_total=2,
        assist_person_id=WALLACE,
        assist_player_name_initial="C. Wallace",
        assist_total=1,
        score_home="2",
        score_away="4",
        description="C. Holmgren 12' Step Back Jump Shot (2 PTS) (C. Wallace 1 AST)",
    ),
    _chet(
        12,
        clock="PT09M39.00S",
        time_actual=_stamp(0, 20, 10),
        action_type="2pt",
        sub_type="Layup",
        shot_result="Missed",
        is_field_goal=1,
        x=12.1,
        y=38.0,
        x_legacy=-61,
        y_legacy=57,
        shot_distance=8.1,
        score_home="2",
        score_away="4",
        description="MISS C. Holmgren 8' driving floating Layup",
    ),
    _sub(
        _chet,
        41,
        "out",
        "PT06M33.00S",
        _stamp(0, 25, 40),
        description="SUB out: C. Holmgren",
    ),
    _sub(
        _okc,
        42,
        "in",
        "PT06M33.00S",
        _stamp(0, 25, 40),
        person_id=MCCAIN,
        player_name_i="J. McCain",
        description="SUB in: J. McCain",
    ),
    _sub(
        _okc,
        62,
        "out",
        "PT04M24.00S",
        _stamp(0, 29, 0),
        person_id=WALLACE,
        player_name_i="C. Wallace",
        description="SUB out: C. Wallace",
    ),
    _sub(
        _chet,
        63,
        "in",
        "PT04M24.00S",
        _stamp(0, 29, 0),
        description="SUB in: C. Holmgren",
    ),
    _sub(
        _sas,
        65,
        "out",
        "PT04M24.00S",
        _stamp(0, 29, 0),
        person_id=VASSELL,
        player_name_i="D. Vassell",
        description="SUB out: D. Vassell",
    ),
    _sub(
        _sas,
        66,
        "in",
        "PT04M24.00S",
        _stamp(0, 29, 0),
        person_id=CASTLE,
        player_name_i="S. Castle",
        description="SUB in: S. Castle",
    ),
    _sub(
        _chet,
        100,
        "out",
        "PT01M12.00S",
        _stamp(0, 43, 30),
        description="SUB out: C. Holmgren",
    ),
    _sub(
        _okc,
        101,
        "in",
        "PT01M12.00S",
        _stamp(0, 43, 30),
        person_id=HARTENSTEIN,
        player_name_i="I. Hartenstein",
        description="SUB in: I. Hartenstein",
    ),
    G7_MARKERS[1],
    G7_MARKERS[2],
    _sub(
        _okc,
        123,
        "out",
        "PT12M00.00S",
        _stamp(0, 49, 0),
        period=2,
        qualifiers=["startperiod"],
        person_id=HARTENSTEIN,
        player_name_i="I. Hartenstein",
        description="SUB out: I. Hartenstein",
    ),
    _sub(
        _chet,
        124,
        "in",
        "PT12M00.00S",
        _stamp(0, 49, 0),
        period=2,
        qualifiers=["startperiod"],
        description="SUB in: C. Holmgren",
    ),
    _sas(
        157,
        period=2,
        clock="PT07M40.00S",
        time_actual=_stamp(0, 58, 48),
        action_type="2pt",
        sub_type="DUNK",
        shot_result="Missed",
        is_field_goal=1,
        x=92.5,
        y=51.2,
        x_legacy=-5,
        y_legacy=10,
        shot_distance=2.0,
        person_id=HARPER,
        player_name="Harper",
        player_name_i="D. Harper",
        block_person_id=CHET,
        block_player_name="C. Holmgren",
        score_home="25",
        score_away="32",
        description="MISS D. Harper driving DUNK - blocked",
    ),
    _chet(
        158,
        period=2,
        clock="PT07M40.00S",
        time_actual=_stamp(0, 58, 48),
        action_type="block",
        score_home="25",
        score_away="32",
        description="C. Holmgren BLOCK (1 BLK)",
    ),
    _chet(
        170,
        period=2,
        clock="PT07M02.00S",
        time_actual=_stamp(1, 0, 10),
        action_type="foul",
        sub_type="personal",
        foul_personal_total=1,
        score_home="25",
        score_away="32",
        description="C. Holmgren shooting personal FOUL (1 PF) (Wembanyama 2 FT)",
    ),
    _chet(
        178,
        period=2,
        clock="PT06M30.00S",
        time_actual=_stamp(1, 1, 0),
        action_type="rebound",
        sub_type="defensive",
        rebound_total=2,
        rebound_defensive_total=1,
        rebound_offensive_total=1,
        score_home="25",
        score_away="34",
        description="C. Holmgren REBOUND (Off:1 Def:1)",
    ),
    _chet(
        187,
        period=2,
        clock="PT05M30.00S",
        time_actual=_stamp(1, 3, 0),
        action_type="freethrow",
        sub_type="1 of 2",
        shot_result="Missed",
        score_home="29",
        score_away="35",
        description="MISS C. Holmgren Free Throw 1 of 2",
    ),
    _chet(
        188,
        period=2,
        clock="PT05M30.00S",
        time_actual=_stamp(1, 3, 10),
        action_type="freethrow",
        sub_type="2 of 2",
        shot_result="Made",
        points_total=3,
        score_home="30",
        score_away="35",
        description="C. Holmgren Free Throw 2 of 2 (3 PTS)",
    ),
    _sas(
        190,
        period=2,
        clock="PT05M10.00S",
        time_actual=_stamp(1, 4, 0),
        action_type="freethrow",
        sub_type="1 of 1",
        shot_result="Made",
        person_id=WEMBY,
        player_name="Wembanyama",
        player_name_i="V. Wembanyama",
        points_total=10,
        score_home="30",
        score_away="36",
        description="V. Wembanyama Free Throw 1 of 1 (10 PTS)",
    ),
    _okc(
        195,
        period=2,
        clock="PT04M50.00S",
        time_actual=_stamp(1, 4, 40),
        action_type="2pt",
        sub_type="Layup",
        shot_result="Made",
        is_field_goal=1,
        x=7.2,
        y=48.0,
        x_legacy=10,
        y_legacy=15,
        shot_distance=3.2,
        person_id=WALLACE,
        player_name="Wallace",
        player_name_i="C. Wallace",
        points_total=4,
        assist_person_id=CHET,
        assist_player_name_initial="C. Holmgren",
        assist_total=1,
        score_home="32",
        score_away="36",
        description="C. Wallace 3' Layup (4 PTS) (C. Holmgren 1 AST)",
    ),
    _chet(
        200,
        period=2,
        clock="PT04M00.00S",
        time_actual=_stamp(1, 6, 0),
        action_type="turnover",
        sub_type="lost ball",
        turnover_total=1,
        score_home="32",
        score_away="36",
        description="C. Holmgren lost ball TURNOVER (1 TO)",
    ),
    _sas(
        209,
        period=2,
        clock="PT03M20.00S",
        time_actual=_stamp(1, 7, 30),
        action_type="turnover",
        sub_type="bad pass",
        person_id=CASTLE,
        player_name="Castle",
        player_name_i="S. Castle",
        turnover_total=1,
        steal_person_id=CHET,
        steal_player_name="C. Holmgren",
        score_home="32",
        score_away="36",
        description="S. Castle bad pass TURNOVER (1 TO)",
    ),
    _chet(
        210,
        period=2,
        clock="PT03M20.00S",
        time_actual=_stamp(1, 7, 30),
        action_type="steal",
        score_home="32",
        score_away="36",
        description="C. Holmgren STEAL (1 STL)",
    ),
    _sas(
        230,
        period=2,
        clock="PT02M00.00S",
        time_actual=_stamp(1, 10, 0),
        action_type="timeout",
        sub_type="full",
        qualifiers=["team", "mandatory"],
        score_home="32",
        score_away="36",
        description="SAS Timeout",
    ),
    # The substitution the feed logs at the timeout's end, on its second
    _sub(
        _sas,
        232,
        "out",
        "PT02M00.00S",
        _stamp(1, 12, 30),
        period=2,
        person_id=CASTLE,
        player_name_i="S. Castle",
        score_home="32",
        score_away="36",
        description="SUB out: S. Castle",
    ),
    _sas(
        240,
        period=2,
        clock="PT01M50.00S",
        time_actual=_stamp(1, 13, 0),
        action_type="3pt",
        sub_type="Jump Shot",
        shot_result="Missed",
        is_field_goal=1,
        x=70.3,
        y=90.1,
        x_legacy=100,
        y_legacy=200,
        shot_distance=25.4,
        person_id=VASSELL,
        player_name="Vassell",
        player_name_i="D. Vassell",
        score_home="32",
        score_away="36",
        description="MISS D. Vassell 25' 3PT",
    ),
    _sas(
        245,
        period=2,
        clock="PT00M01.00S",
        time_actual=_stamp(1, 18, 58),
        action_type="heave",
        score_home="32",
        score_away="36",
        description="SAS heave",
    ),
    G7_MARKERS[3],
    G7_MARKERS[4],
    _chet(
        312,
        period=3,
        clock="PT05M00.00S",
        time_actual=_stamp(1, 47, 0),
        action_type="rebound",
        sub_type="defensive",
        rebound_total=3,
        rebound_defensive_total=2,
        rebound_offensive_total=1,
        score_home="60",
        score_away="61",
        description="C. Holmgren REBOUND (Off:1 Def:2)",
    ),
    G7_MARKERS[5],
    G7_MARKERS[6],
    _sub(
        _chet,
        394,
        "out",
        "PT12M00.00S",
        _stamp(2, 17, 0),
        period=4,
        qualifiers=["startperiod"],
        description="SUB out: C. Holmgren",
    ),
    _sub(
        _okc,
        395,
        "in",
        "PT12M00.00S",
        _stamp(2, 17, 0),
        period=4,
        qualifiers=["startperiod"],
        person_id=HARTENSTEIN,
        player_name_i="I. Hartenstein",
        description="SUB in: I. Hartenstein",
    ),
    G7_MARKERS[7],
    _action(
        508,
        period=4,
        clock="PT00M00.00S",
        time_actual=_stamp(2, 49, 2),
        action_type="game",
        sub_type="end",
        description="Game End",
    ),
]


@pytest.fixture
def g7_game() -> pl.DataFrame:
    return stamp_wall_clock(_pbp(G7_PLAYS))


@pytest.fixture
def g7_clock(g7_game, g7_periods) -> pl.DataFrame:
    return game_clock(g7_game, g7_periods)


@pytest.fixture
def g7_plays(g7_game, g7_periods) -> pl.DataFrame:
    return build_plays(g7_game, g7_periods, CHET)


def _by_action(frame: pl.DataFrame, action_number: int) -> dict:
    return frame.filter(pl.col("action_number") == action_number).row(0, named=True)


class TestAlignComments:
    """Wall clock back to game seconds, with a phase."""

    def test_interpolates_between_the_plays_either_side(self, g7_periods, g7_clock):
        """Halfway between the made shot (second 79) and the miss (second
        141) on the wall is halfway between them on the game clock."""
        shot, miss = _epoch(0, 18, 40), _epoch(0, 20, 10)

        aligned = align_comments(
            _comments(shot, (shot + miss) // 2, miss), g7_periods, g7_clock
        )

        assert aligned["phase"].to_list() == ["live"] * 3
        assert aligned["game_seconds"].to_list() == [79, 110, 141]
        assert aligned["period"].to_list() == [1, 1, 1]

    def test_a_stoppage_is_flat(self, g7_periods, g7_clock):
        """The timeout at 2:00 and the substitution at its end share second
        1,320, so a comment posted during it takes that second; after the
        substitution the ten seconds to the next shot are spread."""
        timeout, sub, shot = _epoch(1, 10), _epoch(1, 12, 30), _epoch(1, 13)

        aligned = align_comments(
            _comments(timeout + 60, sub, sub + 15, shot), g7_periods, g7_clock
        )

        assert aligned["game_seconds"].to_list() == [1320, 1320, 1325, 1330]

    def test_the_markers_own_seconds_are_live(self, g7_periods, g7_clock):
        """Tip-off's second is second 0 of the period; the buzzer's is its
        last, still live."""
        start, end = g7_periods["start_wall"][0], g7_periods["end_wall"][0]

        aligned = align_comments(_comments(start, end), g7_periods, g7_clock)

        assert aligned["phase"].to_list() == ["live", "live"]
        assert aligned["game_seconds"].to_list() == [0, 720]

    def test_break_pins_to_the_period_just_played(self, g7_periods, g7_clock):
        """A halftime comment sits at the end of Q2, period 2."""
        halftime = g7_periods["end_wall"][1] + 300

        aligned = align_comments(_comments(halftime), g7_periods, g7_clock)

        assert aligned.row(0, named=True) | {} == {
            "comment_id": "c0",
            "game_id": GAME,
            "created_utc": halftime,
            "phase": "break",
            "game_seconds": 1440,
            "period": 2,
        }

    def test_before_tip_off_is_pre_at_zero(self, g7_periods, g7_clock):
        """Pre-game chatter keeps its timestamp and sits at second 0."""
        aligned = align_comments(
            _comments(g7_periods["start_wall"][0] - 1), g7_periods, g7_clock
        )

        assert aligned["phase"][0] == "pre"
        assert aligned["game_seconds"][0] == 0
        assert aligned["period"][0] is None

    def test_after_the_buzzer_is_post_at_the_end(self, g7_periods, g7_clock):
        """Post-game chatter sits at the game's last second, no period."""
        aligned = align_comments(
            _comments(g7_periods["end_wall"][3] + 1), g7_periods, g7_clock
        )

        assert aligned["phase"][0] == "post"
        assert aligned["game_seconds"][0] == 2880
        assert aligned["period"][0] is None

    def test_row_order_and_columns_are_kept(self, g7_periods, g7_clock):
        """Input order survives; the three placement columns are appended."""
        later, earlier = g7_periods["start_wall"][2] + 60, g7_periods["start_wall"][0]

        aligned = align_comments(_comments(later, earlier), g7_periods, g7_clock)

        assert aligned["comment_id"].to_list() == ["c0", "c1"]
        assert aligned.columns == [
            "comment_id",
            "game_id",
            "created_utc",
            "game_seconds",
            "phase",
            "period",
        ]

    def test_a_period_starting_the_second_after_the_last_has_no_break(self):
        """Stamped back to back, period 2 opens the second after period 1
        ends: a comment ten minutes into it is live in period 2, not
        pinned to a break that never happened."""
        markers = [
            _marker(1, "start", _stamp(0, 17), 1),
            _marker(1, "end", _stamp(0, 46), 121),
            _marker(2, "start", _stamp(0, 46, 1), 122),
            _marker(2, "end", _stamp(1, 16), 250),
        ]
        pbp = stamp_wall_clock(_pbp(markers))
        periods = build_periods(pbp)

        aligned = align_comments(
            _comments(_epoch(0, 56, 1)), periods, game_clock(pbp, periods)
        )

        assert aligned["phase"][0] == "live"
        assert aligned["period"][0] == 2
        assert aligned["game_seconds"][0] == 960

    def test_two_games_align_on_their_own_clocks(self):
        """A comment maps through its own game's rows."""
        january = date(2026, 1, 15)
        other = [
            _marker(1, "start", _stamp(0, 10, day=january), 1, game_id=OTHER),
            _marker(1, "end", _stamp(0, 40, day=january), 60, game_id=OTHER),
        ]
        pbp = stamp_wall_clock(_pbp([*G7_MARKERS, *other]))
        periods = build_periods(pbp)
        clock = game_clock(pbp, periods)
        other_start = _epoch(0, 10, day=january)
        comments = pl.concat(
            [_comments(other_start + 900, game_id=OTHER), _comments(other_start + 900)]
        )

        aligned = align_comments(comments, periods, clock)

        assert aligned["phase"].to_list() == ["live", "pre"]
        assert aligned["game_seconds"].to_list() == [360, 0]


class TestPlacePlays:
    """Game seconds from the period and the clock."""

    def test_game_seconds(self, g7_periods):
        """Six minutes left in Q2 is second 1,080."""
        plays = _pbp([_action(200, period=2, clock="PT06M00.00S")])

        placed = place_plays(plays, g7_periods)

        assert placed["game_seconds"][0] == 1080
        assert placed.columns == [*LIVE_PLAY_BY_PLAY_SCHEMA.names(), "game_seconds"]

    def test_period_ends_are_the_period_bounds(self, g7_periods):
        """The first and last second of a period are its bounds."""
        plays = _pbp(
            [
                _action(251, period=3, clock="PT12M00.00S"),
                _action(392, period=3, clock="PT00M00.00S"),
            ]
        )

        placed = place_plays(plays, g7_periods)

        assert placed["game_seconds"].to_list() == [1440, 2160]

    def test_tenths_round_to_the_second(self, g7_periods):
        """PT00M40.20S in Q1 is second 680, not a float."""
        placed = place_plays(_pbp([_action(clock="PT00M40.20S")]), g7_periods)

        assert placed["game_seconds"][0] == 680
        assert placed["game_seconds"].dtype == pl.Int64

    def test_play_in_an_unmarked_period_raises(self, g7_periods):
        """A period the markers do not cover has no clock to place on."""
        plays = _pbp([_action(600, period=5, clock="PT04M00.00S")])

        with pytest.raises(RecapError, match="period 5 has no markers"):
            place_plays(plays, g7_periods)

    def test_malformed_clock_raises(self, g7_periods):
        """A clock that does not parse names its action."""
        plays = _pbp([_action(77, clock="6:00")])

        with pytest.raises(RecapError, match="'6:00' does not parse"):
            place_plays(plays, g7_periods)


class TestGameClock:
    """The wall-clock to game-seconds mapping, one row per stamped second."""

    def test_one_row_per_second_the_last_in_feed_order(self, g7_clock):
        """The shot and its block share a second: one row, on their second."""
        assert g7_clock["wall_clock"].n_unique() == g7_clock.height
        at_block = g7_clock.filter(pl.col("wall_clock") == _epoch(0, 58, 48))
        assert at_block["game_seconds"].to_list() == [980]

    def test_sorted_and_monotone(self, g7_clock):
        """Wall clock ascends, and game seconds never run backwards."""
        assert g7_clock["wall_clock"].is_sorted()
        assert g7_clock["game_seconds"].is_sorted()

    def test_the_closing_row_is_not_on_the_clock(self, g7_clock):
        """The feed's game-end row adds nothing after the last marker."""
        assert g7_clock["wall_clock"].max() == _epoch(2, 49)


class TestDeriveKind:
    """Every play's kind, and whose play it is."""

    @pytest.fixture
    def kinds(self, g7_game) -> pl.DataFrame:
        return derive_kind(g7_game, CHET)

    @pytest.mark.parametrize(
        "action_number,kind",
        [
            (1, "period_start"),
            (121, "period_end"),
            (158, "block"),
            (210, "steal"),
            (41, "sub_out"),
            (63, "sub_in"),
            (42, "sub_in"),
            (8, "shot"),
            (157, "shot"),
            (240, "shot"),
            (245, "heave"),
            (188, "free_throw"),
            (178, "rebound"),
            (200, "turnover"),
            (170, "foul"),
            (230, "timeout"),
            (2, "jump_ball"),
        ],
    )
    def test_kind(self, kinds, action_number, kind):
        """The feed's action type under the recap's vocabulary."""
        assert _by_action(kinds, action_number)["kind"] == kind

    def test_unknown_action_type_is_other(self):
        """A type the vocabulary does not name is kept as other."""
        kinds = derive_kind(_pbp([_action(9, action_type="instantreplay")]), CHET)
        assert kinds["kind"][0] == "other"

    def test_is_focus_covers_his_rows_check_ins_and_assists(self, kinds):
        """His own rows, the substitution that brings him on (it names him),
        and the teammate's made shot that credits him."""
        assert _by_action(kinds, 8)["is_focus"] is True
        assert _by_action(kinds, 63)["is_focus"] is True
        assert _by_action(kinds, 124)["is_focus"] is True
        assert _by_action(kinds, 195)["is_focus"] is True

    def test_other_players_rows_are_not_his(self, kinds):
        """The shot he blocked, a teammate's check-in and an opponent's free throw."""
        assert _by_action(kinds, 157)["is_focus"] is False
        assert _by_action(kinds, 42)["is_focus"] is False
        assert _by_action(kinds, 190)["is_focus"] is False


class TestPairPlays:
    """A block or steal points at the play it ended: the row before it."""

    @pytest.fixture
    def paired(self, g7_game) -> pl.DataFrame:
        return pair_plays(derive_kind(g7_game, CHET))

    def test_block_takes_the_shots_number_and_location(self, paired):
        """The block draws where Harper's dunk was attempted."""
        block = _by_action(paired, 158)
        assert block["paired_action_number"] == 157
        assert (block["x"], block["y"], block["shot_distance"]) == (92.5, 51.2, 2.0)

    def test_steal_takes_the_turnovers_number_only(self, paired):
        """A turnover has no location to borrow."""
        steal = _by_action(paired, 210)
        assert steal["paired_action_number"] == 209
        assert (steal["x"], steal["y"]) == (None, None)

    def test_other_rows_are_unpaired_and_untouched(self, paired):
        """A shot keeps its own coordinates and pairs with nothing."""
        shot = _by_action(paired, 8)
        assert shot["paired_action_number"] is None
        assert (shot["x"], shot["y"]) == (18.4, 62.1)
        assert paired.height == len(G7_PLAYS)

    def test_block_not_after_its_shot_raises(self, g7_game):
        """A block whose shot is not the row before it is a feed defect."""
        orphan = g7_game.filter(pl.col("action_number") != 157)

        with pytest.raises(
            RecapError, match="block at action 158 does not follow the play it ended"
        ):
            pair_plays(derive_kind(orphan, CHET))

    def test_shot_blocked_by_someone_else_raises(self, g7_game):
        """The row before names another blocker: not this block's shot."""
        misnamed = g7_game.with_columns(
            pl.when(pl.col("action_number") == 157)
            .then(WEMBY)
            .otherwise(pl.col("block_person_id"))
            .alias("block_person_id")
        )

        with pytest.raises(RecapError, match="block at action 158"):
            pair_plays(derive_kind(misnamed, CHET))


class TestBuildPlays:
    """What a recap ships: the game's feed, in the contract's shape."""

    def test_conforms_to_the_plays_frame(self, g7_plays):
        """Column names, dtypes, order and nullability are the contract's."""
        validate_schema(g7_plays.drop("game_id"), RECAP_PLAYS_SCHEMA, "plays")
        validate_nullability(
            g7_plays.drop("game_id"), RECAP_NULLABLE_COLUMNS["plays"], "plays"
        )

    def test_in_feed_order(self, g7_plays):
        """The rows keep the feed's order, whatever order they arrived in."""
        assert g7_plays["action_number"].is_sorted()

    def test_every_row_but_the_closing_one(self, g7_plays):
        """The feed whole: nothing is dropped but the game-end row."""
        kept = g7_plays["action_number"].to_list()
        assert kept == [row["action_number"] for row in G7_PLAYS[:-1]]
        assert 508 not in kept

    def test_other_players_rows_reach_the_frame(self, g7_plays):
        """Wembanyama's free throw, Castle's turnover and a teammate's
        check-in are in the frame and are not the focus player's."""
        free_throw = _by_action(g7_plays, 190)
        assert (free_throw["kind"], free_throw["person_id"]) == ("free_throw", WEMBY)
        assert (free_throw["made"], free_throw["shot_value"]) == (True, 1)
        check_in = _by_action(g7_plays, 42)
        assert (check_in["kind"], check_in["person_id"]) == ("sub_in", MCCAIN)
        assert _by_action(g7_plays, 209)["kind"] == "turnover"
        assert not any(_by_action(g7_plays, n)["is_focus"] for n in (190, 42, 209, 232))

    def test_a_rebound_by_another_player_reaches_the_frame(self, g7_game, g7_periods):
        """A rebound names its player and his team, whoever he is."""
        rebound = _sas(
            241,
            period=2,
            clock="PT01M48.00S",
            time_actual=_stamp(1, 13, 2),
            action_type="rebound",
            sub_type="offensive",
            person_id=WEMBY,
            player_name_i="V. Wembanyama",
        )
        plays = build_plays(
            stamp_wall_clock(_pbp([*G7_PLAYS, rebound])), g7_periods, CHET
        )

        row = _by_action(plays, 241)
        assert (row["kind"], row["sub_type"]) == ("rebound", "offensive")
        assert (row["person_id"], row["team_tricode"]) == (WEMBY, "SAS")
        assert row["is_focus"] is False

    def test_full_court_positions_pass_through(self, g7_plays):
        """A shot keeps the feed's position; a row the feed does not locate
        has none."""
        assert (_by_action(g7_plays, 8)["x"], _by_action(g7_plays, 8)["y"]) == (
            18.4,
            62.1,
        )
        assert _by_action(g7_plays, 240)["x"] == 70.3
        assert _by_action(g7_plays, 178)["x"] is None
        assert _by_action(g7_plays, 245)["x"] is None

    def test_an_assist_id_lands_on_its_made_shot(self, g7_plays):
        """Wallace on Holmgren's jumper, Holmgren on Wallace's layup; null
        on a miss and off a shot."""
        assert _by_action(g7_plays, 8)["assist_person_id"] == WALLACE
        assert _by_action(g7_plays, 195)["assist_person_id"] == CHET
        assert _by_action(g7_plays, 12)["assist_person_id"] is None
        assert _by_action(g7_plays, 178)["assist_person_id"] is None

    def test_a_steal_pairs_with_its_turnover(self, g7_plays):
        """Castle's turnover is in the frame, so the pairing resolves."""
        assert _by_action(g7_plays, 210)["paired_action_number"] == 209

    def test_focus_player_without_an_action_raises(self, g7_game, g7_periods):
        """A player with no row in the game cannot anchor a recap."""
        with pytest.raises(RecapError, match=f"{GAME}: player 999 has no action"):
            build_plays(g7_game, g7_periods, 999)

    def test_score_on_every_row(self, g7_plays):
        """The feed writes the score on every row; a rebound reads 25-34."""
        assert (
            _by_action(g7_plays, 178)["score_home"],
            _by_action(g7_plays, 178)["score_away"],
        ) == (25, 34)
        assert g7_plays["score_home"].dtype == pl.Int64
        assert g7_plays["score_home"].null_count() == 0

    def test_made_is_null_off_a_shot_and_false_on_a_heave(self, g7_plays):
        """True, False, null when nothing was shot; a heave is a miss."""
        assert _by_action(g7_plays, 8)["made"] is True
        assert _by_action(g7_plays, 157)["made"] is False
        assert _by_action(g7_plays, 178)["made"] is None
        assert _by_action(g7_plays, 245)["made"] is False

    def test_shot_value_from_the_action_type(self, g7_plays):
        """3, 2, 1, and 0 off a shot."""
        assert _by_action(g7_plays, 240)["shot_value"] == 3
        assert _by_action(g7_plays, 8)["shot_value"] == 2
        assert _by_action(g7_plays, 188)["shot_value"] == 1
        assert _by_action(g7_plays, 178)["shot_value"] == 0

    def test_both_clocks(self, g7_plays):
        """The block sits at Q2 4:20 elapsed, and on its own stamp."""
        block = _by_action(g7_plays, 158)
        assert block["game_seconds"] == 720 + 260
        assert block["wall_clock"] == _epoch(0, 58, 48)

    def test_sub_in_carries_the_player_coming_in(self, g7_plays):
        """The check-in row is his: his id, his name."""
        check_in = _by_action(g7_plays, 63)
        assert check_in["kind"] == "sub_in"
        assert check_in["person_id"] == CHET
        assert check_in["is_focus"] is True

    def test_team_rows_carry_no_player(self, g7_plays):
        """A timeout names the team; a marker names nothing."""
        assert _by_action(g7_plays, 230)["player_name_i"] is None
        assert _by_action(g7_plays, 230)["team_tricode"] == "SAS"
        assert _by_action(g7_plays, 1)["team_tricode"] is None


def _stints_of(stints: pl.DataFrame, person_id: int) -> list[tuple]:
    """One player's intervals as (period, start_seconds, end_seconds)."""
    return (
        stints.filter(pl.col("person_id") == person_id)
        .select("period", "start_seconds", "end_seconds")
        .rows()
    )


def _stint_frame(rows: list[tuple]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=RECAP_STINTS_SCHEMA, orient="row")


class TestBuildStints:
    """On-court intervals from the substitutions and the period openings."""

    def test_stints(self, g7_plays, g7_periods):
        """Started Q1 and left at 6:33 (first sub takes him off), back at 4:24
        to 1:12; checked in at the Q2 break for all of Q2; carried on through
        Q3 on a rebound alone; checked out at the Q4 break for none of it."""
        stints = build_stints(g7_plays, g7_periods)

        assert stints.schema == RECAP_STINTS_SCHEMA
        assert _stints_of(stints, CHET) == [
            (1, 0, 327),
            (1, 456, 648),
            (2, 720, 1440),
            (3, 1440, 2160),
        ]

    def test_a_starter_and_a_check_in_on_opposite_teams(self, g7_plays, g7_periods):
        """Holmgren starts for Oklahoma City; Castle checks in for San
        Antonio at 4:24, carries across the break and leaves at Q2 2:00."""
        stints = build_stints(g7_plays, g7_periods)

        assert _stints_of(stints, CASTLE) == [(1, 456, 720), (2, 720, 1320)]
        teams = dict(stints.select("person_id", "team_tricode").unique().rows())
        assert (teams[CHET], teams[CASTLE]) == ("OKC", "SAS")

    def test_every_player_with_a_stint_and_no_one_else(self, g7_plays, g7_periods):
        """Harper and Wembanyama act only in Q2 with no substitution, so
        they read as bench and have no row."""
        stints = build_stints(g7_plays, g7_periods)

        assert set(stints["person_id"].to_list()) == {
            CHET,
            MCCAIN,
            WALLACE,
            HARTENSTEIN,
            VASSELL,
            CASTLE,
        }

    def test_in_game_order(self, g7_plays, g7_periods):
        """By when the interval opens, then by player."""
        stints = build_stints(g7_plays, g7_periods)

        assert stints.rows() == sorted(stints.rows(), key=lambda row: (row[3], row[0]))

    def test_a_check_in_at_the_break_closes_nothing(self, g7_plays, g7_periods):
        """Hartenstein comes on at 1:12, goes off at the Q2 break on the
        period's first second, and returns for Q4."""
        stints = build_stints(g7_plays, g7_periods)

        assert _stints_of(stints, HARTENSTEIN) == [(1, 648, 720), (4, 2160, 2880)]

    def test_without_substitutions_the_state_carries_from_the_first_period(
        self, g7_periods
    ):
        """On the floor in Q1 on a rebound, never substituted: every period."""
        rows = [
            *G7_MARKERS,
            _chet(
                3,
                clock="PT06M00.00S",
                time_actual=_stamp(0, 30),
                action_type="rebound",
                sub_type="defensive",
                rebound_total=1,
            ),
        ]
        plays = build_plays(stamp_wall_clock(_pbp(rows)), g7_periods, CHET)

        stints = build_stints(plays, g7_periods)

        assert stints.rows() == [
            (CHET, "OKC", 1, 0, 720),
            (CHET, "OKC", 2, 720, 1440),
            (CHET, "OKC", 3, 1440, 2160),
            (CHET, "OKC", 4, 2160, 2880),
        ]

    def test_an_assist_is_a_play_on_the_floor(self, g7_periods):
        """Wallace has no row of his own: the assist on Holmgren's make puts
        him on the floor."""
        rows = [
            *G7_MARKERS,
            _chet(
                3,
                clock="PT06M00.00S",
                time_actual=_stamp(0, 30),
                action_type="2pt",
                shot_result="Made",
                assist_person_id=WALLACE,
            ),
        ]
        plays = build_plays(stamp_wall_clock(_pbp(rows)), g7_periods, CHET)

        stints = build_stints(plays, g7_periods)

        assert _stints_of(stints, WALLACE)[0] == (1, 0, 720)
        assert stints.filter(pl.col("person_id") == WALLACE)["team_tricode"][0] == "OKC"

    @pytest.mark.parametrize(
        "action_type,sub_type", [("foul", "technical"), ("ejection", "")]
    )
    def test_a_call_on_the_bench_is_not_a_play_on_the_floor(
        self, g7_periods, action_type, sub_type
    ):
        """A technical or an ejection can be called on a player who is
        sitting: McCain's alone gives him no stint."""
        rows = [
            *G7_MARKERS,
            _chet(
                3,
                clock="PT06M00.00S",
                time_actual=_stamp(0, 30),
                action_type="rebound",
                sub_type="defensive",
            ),
            _okc(
                4,
                clock="PT05M00.00S",
                time_actual=_stamp(0, 31),
                action_type=action_type,
                sub_type=sub_type,
                person_id=MCCAIN,
                player_name_i="J. McCain",
            ),
        ]
        plays = build_plays(stamp_wall_clock(_pbp(rows)), g7_periods, CHET)

        stints = build_stints(plays, g7_periods)

        assert set(stints["person_id"].to_list()) == {CHET}

    def test_a_foul_the_feed_does_not_type_is_a_play_on_the_floor(self, g7_periods):
        """Only a technical or an ejection is discounted; a foul with no
        sub type still puts him on the floor."""
        rows = [
            *G7_MARKERS,
            _chet(
                3,
                clock="PT06M00.00S",
                time_actual=_stamp(0, 30),
                action_type="foul",
                sub_type=None,
            ),
        ]
        plays = build_plays(stamp_wall_clock(_pbp(rows)), g7_periods, CHET)

        assert _stints_of(build_stints(plays, g7_periods), CHET)[0] == (1, 0, 720)

    def test_bench_player_opens_off_the_floor(self, g7_periods):
        """His first substitution brings him on at 6:00: on from there,
        carried across the break, off at Q2 8:00."""
        rows = [
            *G7_MARKERS,
            _sub(_chet, 3, "in", "PT06M00.00S", _stamp(0, 30)),
            _sub(_chet, 130, "out", "PT08M00.00S", _stamp(0, 57), period=2),
        ]
        plays = build_plays(stamp_wall_clock(_pbp(rows)), g7_periods, CHET)

        stints = build_stints(plays, g7_periods)

        assert _stints_of(stints, CHET) == [(1, 360, 720), (2, 720, 960)]

    def test_a_check_out_while_read_as_off_opens_from_the_period_start(
        self, g7_periods
    ):
        """No action and no substitution in Q1 reads as bench, so Q1 is
        lost; his Q2 check-out proves he was on from the break."""
        rows = [
            *G7_MARKERS,
            _sub(_chet, 130, "out", "PT08M00.00S", _stamp(0, 57), period=2),
        ]
        plays = build_plays(stamp_wall_clock(_pbp(rows)), g7_periods, CHET)

        assert _stints_of(build_stints(plays, g7_periods), CHET) == [(2, 720, 960)]


class TestStintSeconds:
    """Seconds on the floor per player."""

    def test_seconds_per_player(self):
        """All 48 minutes for one, a quarter for the other, each with his team."""
        stints = _stint_frame(
            [
                (CHET, "OKC", 1, 0, 720),
                (CASTLE, "SAS", 1, 0, 720),
                (CHET, "OKC", 2, 720, 2880),
            ]
        )

        assert stint_seconds(stints).rows() == [
            (CHET, "OKC", 2880),
            (CASTLE, "SAS", 720),
        ]

    def test_no_stints_is_no_rows(self):
        assert stint_seconds(RECAP_STINTS_SCHEMA.to_frame()).height == 0


class TestMinutesOff:
    """Stint seconds against the box score's whole minutes."""

    @pytest.mark.parametrize(
        "seconds,box_minutes,off",
        [
            (1830, 31, 0),  # 30:30 that the box score rounded up
            (2310, 38, 0),  # 38:30 that it rounded down
            (1829, 30, 0),
            (1831, 30, 1),
            (1769, 30, -1),
            (1890, 30, 1),  # a minute and a half over is one whole minute off
            (1710, 30, -1),
            (2880, 34, 14),
            (0, 5, -5),
        ],
    )
    def test_half_a_minute_or_less_is_agreement(self, seconds, box_minutes, off):
        """The box score rounds a clock kept in tenths, so whole seconds
        within half a minute of it agree; past that, whole minutes off."""
        frame = pl.DataFrame({"seconds": [seconds], "minutes": [box_minutes]})

        assert (
            frame.select(minutes_off(pl.col("seconds"), pl.col("minutes"))).item()
            == off
        )


FIVE = (CHET, WALLACE, HARTENSTEIN, MCCAIN, 99)


class TestFloorGaps:
    """Where the stints do not put five players per team on the floor."""

    def test_five_all_game_is_no_gap(self, g7_periods):
        """Each interval closes on the buzzer and reopens on the same second."""
        stints = _stint_frame(
            [
                (player, "OKC", period, start, start + 720)
                for player in FIVE
                for period, start in ((1, 0), (2, 720), (3, 1440), (4, 2160))
            ]
        )

        assert floor_gaps(stints, g7_periods, ["OKC"]).height == 0

    def test_a_swap_on_one_second_is_no_gap(self, g7_periods):
        """One out and one in at 5:00 of Q1 leaves five throughout."""
        stints = _stint_frame(
            [
                *((player, "OKC", 1, 0, 2880) for player in FIVE[:4]),
                (99, "OKC", 1, 0, 300),
                (98, "OKC", 1, 300, 2880),
            ]
        )

        assert floor_gaps(stints, g7_periods, ["OKC"]).height == 0

    def test_a_sixth_player_is_reported_with_its_span(self, g7_periods):
        """A sixth on the floor from 1:40 to 3:20 of Q1."""
        stints = _stint_frame(
            [
                *((player, "OKC", 1, 0, 2880) for player in FIVE),
                (98, "OKC", 1, 100, 200),
            ]
        )

        assert floor_gaps(stints, g7_periods, ["OKC"]).rows() == [("OKC", 100, 200, 6)]

    def test_a_missing_player_is_reported_from_tip_off(self, g7_periods):
        """Four until the fifth's first interval opens; the other team's
        five are untouched."""
        stints = _stint_frame(
            [
                *((player, "OKC", 1, 0, 2880) for player in FIVE[:4]),
                (99, "OKC", 1, 50, 2880),
                *((player, "SAS", 1, 0, 2880) for player in (1, 2, 3, 4, 5)),
            ]
        )

        assert floor_gaps(stints, g7_periods, ["OKC", "SAS"]).rows() == [
            ("OKC", 0, 50, 4)
        ]

    def test_a_team_with_no_stint_reads_none_all_game(self, g7_periods):
        """A team the feed names and the stints never do is one gap, tip-off
        to the last buzzer."""
        stints = _stint_frame([(player, "OKC", 1, 0, 2880) for player in FIVE])

        assert floor_gaps(stints, g7_periods, ["OKC", "SAS"]).rows() == [
            ("SAS", 0, 2880, 0)
        ]

    def test_one_gap_across_other_teams_edges(self, g7_periods):
        """A sixth all game is one span, however many substitutions the
        five make under him."""
        stints = _stint_frame(
            [
                *((player, "OKC", 1, 0, 2880) for player in FIVE[:4]),
                (99, "OKC", 1, 0, 300),
                (98, "OKC", 1, 300, 2880),
                (97, "OKC", 1, 0, 2880),
            ]
        )

        assert floor_gaps(stints, g7_periods, ["OKC"]).rows() == [("OKC", 0, 2880, 6)]


# --- Comments, anchors, the document ---------------------------------------

LIVE, SPLIT, PGT = "t3_live", "t3_split", "t3_pgt"
CHET_NAME = "Chet Holmgren"


def _fact_row(
    comment_id: str,
    created_utc: int,
    *,
    sentiment: str = "neg",
    score: int = 1,
    player: str | None = CHET_NAME,
    body: str = "chet",
    link_id: str = LIVE,
    fan_team: str | None = "Oklahoma City Thunder",
) -> dict:
    return {
        "comment_id": comment_id,
        "link_id": link_id,
        "created_utc": created_utc,
        "sentiment": sentiment,
        "score": score,
        "fan_team": fan_team,
        "attributed_player": player,
        "body": body,
    }


FACT_SCHEMA = {
    "comment_id": pl.String,
    "link_id": pl.String,
    "created_utc": pl.Int64,
    "sentiment": pl.String,
    "score": pl.Int64,
    "fan_team": pl.String,
    "attributed_player": pl.String,
    "body": pl.String,
}


def _fact(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=FACT_SCHEMA)


def _posts() -> pl.DataFrame:
    rows = [
        (
            LIVE,
            "Game Thread: SAS vs OKC",
            1_000,
            100,
            40_000,
            "Game Thread",
            "game_thread",
            GAME,
            True,
        ),
        (
            SPLIT,
            "Game Thread: second half",
            1_500,
            50,
            7_000,
            "Game Thread",
            "game_thread",
            GAME,
            False,
        ),
        (
            PGT,
            "[Post Game Thread] Spurs advance",
            9_000,
            90,
            4_000,
            "Post Game Thread",
            "post_game_thread",
            GAME,
            True,
        ),
    ]
    return pl.DataFrame(
        rows,
        schema={
            "post_id": pl.String,
            "title": pl.String,
            "created_utc": pl.Int64,
            "score": pl.Int64,
            "num_comments": pl.Int64,
            "link_flair_text": pl.String,
            "post_type": pl.String,
            "game_id": pl.String,
            "is_primary": pl.Boolean,
        },
        orient="row",
    )


def _games() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": [GAME, OTHER],
            "game_date": [date(2026, 6, 1), date(2026, 1, 15)],
            "home_team": ["Oklahoma City Thunder", "Los Angeles Lakers"],
            "away_team": ["San Antonio Spurs", "Golden State Warriors"],
        },
        schema={
            "game_id": pl.String,
            "game_date": pl.Date,
            "home_team": pl.String,
            "away_team": pl.String,
        },
    )


def _players() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "attributed_player": [CHET_NAME, "Victor Wembanyama"],
            "slug": ["chet-holmgren", "victor-wembanyama"],
            "player_id": [CHET, WEMBY],
        },
        schema={
            "attributed_player": pl.String,
            "slug": pl.String,
            "player_id": pl.Int64,
        },
    )


BOX_STATS = (
    "minutes",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "ftm",
    "fta",
    "oreb",
    "dreb",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
    "pf",
    "pts",
)
# Holmgren's line in the G7 fixture, counted by hand from G7_PLAYS
CHET_LINE = {
    "minutes": 33,
    "fgm": 1,
    "fga": 2,
    "ftm": 1,
    "fta": 2,
    "dreb": 2,
    "reb": 2,
    "ast": 1,
    "stl": 1,
    "blk": 1,
    "tov": 1,
    "pf": 1,
    "pts": 3,
}


def _box_line(player_id: int, name: str, team: str, **stats: int) -> dict:
    """One player's box-score line; a stat not given is 0."""
    return {
        "game_id": GAME,
        "player_id": player_id,
        "player_name": name,
        "team_abbr": team,
        **{stat: stats.get(stat, 0) for stat in BOX_STATS},
    }


def _player_log(*lines: dict) -> pl.DataFrame:
    return pl.DataFrame(
        list(lines),
        schema={
            "game_id": pl.String,
            "player_id": pl.Int64,
            "player_name": pl.String,
            "team_abbr": pl.String,
            **{stat: pl.Int64 for stat in BOX_STATS},
        },
    )


def _team_log(**points: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": [GAME] * len(points),
            "team_abbr": list(points),
            "pts": list(points.values()),
        },
        schema={"game_id": pl.String, "team_abbr": pl.String, "pts": pl.Int64},
    )


def _g7_player_log(minutes: int = 33) -> pl.DataFrame:
    """The G7 box score as far as the focus player: his line alone."""
    return _player_log(
        _box_line(CHET, CHET_NAME, "OKC", **{**CHET_LINE, "minutes": minutes})
    )


G7_TEAM_LOG = _team_log(OKC=5, SAS=1)


STAMPS = RecapStamps(
    season="2025-26",
    generated_at="2026-09-26T12:00:00+00:00",
    config_versions={"recaps": "1.0", "players": "4.6", "teams": "2.3"},
    classifiers={
        "sentiment": {"model": "claude-haiku-4-5-20251001", "prompt_version": "v2"}
    },
)


def _spec(pbp_dir) -> ResolvedSpec:
    return ResolvedSpec(
        game_id=GAME,
        slug="chet-holmgren",
        attributed_player=CHET_NAME,
        player_id=CHET,
        thread_ids=(LIVE, SPLIT),
        room_n=47_000,
        pbp_path=pbp_dir / f"{GAME}.parquet",
    )


@pytest.fixture
def g7_fact(g7_periods) -> pl.DataFrame:
    """Comments around the G7 clock: a Q1 bucket of room noise, a block
    pile-on, a steal with two reactions, halftime, pre and post chatter."""
    q1 = g7_periods["start_wall"][0]
    bucket = (q1 + 600) // 120 * 120
    minute = (_epoch(0, 58, 48) // 60 + 1) * 60
    steal_minute = (_epoch(1, 7, 30) // 60 + 1) * 60
    halftime = g7_periods["end_wall"][1] + 300
    rows = [
        _fact_row("pre1", q1 - 100, body="tip soon", sentiment="neu"),
        _fact_row(
            "r50", bucket + 1, score=50, player="Victor Wembanyama", body="wemby!"
        ),
        _fact_row("r40", bucket + 2, score=40, player=None, body="refs"),
        _fact_row(
            "r30", bucket + 3, score=30, player="Victor Wembanyama", body="quiet"
        ),
        _fact_row("f1", bucket + 4, score=2, body="chet is cooked", link_id=SPLIT),
        _fact_row("b1", minute + 5, body="WHAT A BLOCK by Chet"),
        _fact_row("b2", minute + 10, body="chet block!!!", sentiment="pos"),
        _fact_row("b3", minute + 15, body="that block though"),
        _fact_row("s1", steal_minute + 5, body="chet steal"),
        _fact_row("s2", steal_minute + 9, body="steal!"),
        _fact_row("h1", halftime, body="halftime chet", sentiment="pos"),
        _fact_row("post1", g7_periods["end_wall"][3] + 60, body="gg", sentiment="neu"),
        _fact_row("pgt1", 9_500, body="post game", link_id=PGT),
    ]
    return _fact(rows)


@pytest.fixture
def pbp_dir(tmp_path) -> Path:
    _pbp(G7_PLAYS).write_parquet(
        tmp_path / f"{GAME}.parquet", metadata={"season": "2025-26"}
    )
    return tmp_path


@pytest.fixture
def g7_doc(g7_fact, pbp_dir):
    return build_recap(
        _spec(pbp_dir),
        fact=g7_fact,
        posts=_posts(),
        player_log=_g7_player_log(),
        team_log=G7_TEAM_LOG,
        players=_players(),
        pbp=_pbp(G7_PLAYS),
        stamps=STAMPS,
    )


def _line_of(lines: pl.DataFrame, person_id: int) -> dict:
    return lines.filter(pl.col("person_id") == person_id).row(0, named=True)


class TestBoxLines:
    """Every player's line, counted from the rows as the page counts it."""

    def test_counts_each_stat(self, g7_plays):
        """Holmgren: 1 of 2 from the field, 1 of 2 at the line, two
        defensive rebounds, an assist, a steal, a block, a turnover, a foul."""
        line = _line_of(box_lines(g7_plays), CHET)

        assert (line["team_tricode"], line["player_name_i"]) == ("OKC", "C. Holmgren")
        assert {stat: line[stat] for stat in BOX_STATS[1:]} == {
            **dict.fromkeys(BOX_STATS[1:], 0),
            **{k: v for k, v in CHET_LINE.items() if k != "minutes"},
        }

    def test_a_three_counts_as_a_field_goal_too(self, g7_plays):
        """Vassell's missed three is an attempt on both lines."""
        line = _line_of(box_lines(g7_plays), VASSELL)

        assert (line["fga"], line["fg3a"], line["fgm"], line["pts"]) == (1, 1, 0, 0)

    def test_an_assist_counts_for_the_passer(self, g7_plays):
        """Wallace on Holmgren's jumper; his own layup is two points."""
        line = _line_of(box_lines(g7_plays), WALLACE)

        assert (line["ast"], line["fgm"], line["pts"]) == (1, 1, 2)

    def test_team_rows_are_no_ones(self, g7_plays):
        """The heave and the timeout name a team only: no line, no attempt."""
        lines = box_lines(g7_plays)

        assert 0 not in lines["person_id"].to_list()
        assert lines.filter(pl.col("team_tricode") == "SAS")["fga"].sum() == 2

    def test_a_technical_is_not_a_personal(self, g7_game, g7_periods):
        """His technical leaves him on one personal foul."""
        technical = _chet(
            171,
            period=2,
            clock="PT07M00.00S",
            time_actual=_stamp(1, 0, 20),
            action_type="foul",
            sub_type="technical",
        )
        plays = build_plays(
            stamp_wall_clock(_pbp([*G7_PLAYS, technical])), g7_periods, CHET
        )

        assert _line_of(box_lines(plays), CHET)["pf"] == 1


class TestCheckBox:
    """The rows and the stints against the box score."""

    @pytest.fixture
    def game(self, g7_periods) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Holmgren's rebound and Wembanyama's three in Q1, nobody
        substituted: both play all 48 minutes."""
        rows = [
            *G7_MARKERS,
            _chet(
                3,
                clock="PT06M00.00S",
                time_actual=_stamp(0, 30),
                action_type="rebound",
                sub_type="defensive",
            ),
            _sas(
                4,
                clock="PT05M00.00S",
                time_actual=_stamp(0, 31),
                action_type="3pt",
                shot_result="Made",
                person_id=WEMBY,
                player_name_i="V. Wembanyama",
                score_away="3",
            ),
        ]
        plays = build_plays(stamp_wall_clock(_pbp(rows)), g7_periods, CHET)
        return plays, build_stints(plays, g7_periods)

    CHET_BOX = {"minutes": 48, "dreb": 1, "reb": 1}
    WEMBY_BOX = {"minutes": 48, "fgm": 1, "fga": 1, "fg3m": 1, "fg3a": 1, "pts": 3}

    def _log(self, chet: dict | None = None, *extra: dict) -> pl.DataFrame:
        return _player_log(
            _box_line(CHET, CHET_NAME, "OKC", **(chet or self.CHET_BOX)),
            _box_line(WEMBY, "Victor Wembanyama", "SAS", **self.WEMBY_BOX),
            *extra,
        )

    def test_an_agreeing_box_score_is_no_mismatch(self, game):
        mismatches = check_box(*game, self._log(), _team_log(OKC=0, SAS=3))

        assert mismatches.height == 0
        assert mismatches.columns == [
            "team_tricode",
            "person_id",
            "player",
            "stat",
            "from_feed",
            "in_box",
        ]

    def test_a_line_mismatch_names_the_player_and_the_stat(self, game):
        """The box score credits Holmgren a second defensive rebound."""
        box = self._log({"minutes": 48, "dreb": 2, "reb": 2})

        mismatches = check_box(*game, box, _team_log(OKC=0, SAS=3))

        assert mismatches.rows() == [
            ("OKC", CHET, CHET_NAME, "dreb", 1, 2),
            ("OKC", CHET, CHET_NAME, "reb", 1, 2),
        ]

    def test_minutes_are_checked_with_the_line(self, game):
        """48 stint minutes against 40 in the box score."""
        box = self._log({**self.CHET_BOX, "minutes": 40})

        mismatches = check_box(*game, box, _team_log(OKC=0, SAS=3))

        assert mismatches.rows() == [("OKC", CHET, CHET_NAME, "minutes", 48, 40)]

    def test_reported_minutes_are_the_box_scores_plus_what_they_are_off(self, game):
        """31:30 on the floor against 30 is one minute off, so it reads 31:
        the warning and the registry's minutes_diff cannot disagree."""
        plays, _ = game
        stints = _stint_frame([(CHET, "OKC", 1, 0, 1890), (WEMBY, "SAS", 1, 0, 2880)])
        box = self._log({**self.CHET_BOX, "minutes": 30})

        mismatches = check_box(plays, stints, box, _team_log(OKC=0, SAS=3))

        assert mismatches.rows() == [("OKC", CHET, CHET_NAME, "minutes", 31, 30)]

    @pytest.mark.parametrize("box_minutes", [38, 39])
    def test_minutes_within_half_a_minute_agree(self, game, box_minutes):
        """38:30 on the floor agrees with 38 and with 39: the box score
        rounds a finer clock than the stints hold."""
        plays, _ = game
        stints = _stint_frame([(CHET, "OKC", 1, 0, 2310), (WEMBY, "SAS", 1, 0, 2880)])
        box = self._log({**self.CHET_BOX, "minutes": box_minutes})

        mismatches = check_box(plays, stints, box, _team_log(OKC=0, SAS=3))

        assert mismatches.height == 0

    def test_a_box_line_with_no_row_in_the_feed_is_checked_against_nothing(self, game):
        """Wallace played five minutes by the box score and never appears."""
        wallace = _box_line(WALLACE, "Cason Wallace", "OKC", minutes=5)

        mismatches = check_box(*game, self._log(None, wallace), _team_log(OKC=0, SAS=3))

        assert mismatches.rows() == [("OKC", WALLACE, "Cason Wallace", "minutes", 0, 5)]

    def test_a_player_who_did_not_play_agrees_with_no_line(self, game):
        """A dressed player with zeros, and nothing in the feed: no mismatch."""
        mccain = _box_line(MCCAIN, "Jared McCain", "OKC")

        mismatches = check_box(*game, self._log(None, mccain), _team_log(OKC=0, SAS=3))

        assert mismatches.height == 0

    def test_team_points_are_checked_against_the_final_score(self, game):
        """Three points from the rows against five on the scoreboard."""
        mismatches = check_box(*game, self._log(), _team_log(OKC=0, SAS=5))

        assert mismatches.rows() == [("SAS", 0, None, "pts", 3, 5)]


class TestSelectComments:
    """Every aligned comment, bodies by rule."""

    @pytest.fixture
    def comments(self, g7_fact, g7_periods, g7_clock) -> pl.DataFrame:
        aligned = align_comments(
            g7_fact.filter(pl.col("link_id") != PGT).with_columns(
                pl.lit(GAME).alias("game_id")
            ),
            g7_periods,
            g7_clock,
        )
        return select_comments(aligned, CHET_NAME, _players())

    def test_conforms(self, comments):
        """The contract's columns, order and nullability, sorted by time."""
        validate_schema(comments, RECAP_COMMENTS_SCHEMA, "comments")
        validate_nullability(comments, RECAP_NULLABLE_COLUMNS["comments"], "comments")
        assert comments["created_utc"].is_sorted()

    def test_focus_bodies_are_always_kept(self, comments):
        """His comments carry their body wherever they fall."""
        focus = comments.filter(pl.col("is_focus"))
        assert focus["body"].null_count() == 0
        assert focus["comment_id"].to_list() == [
            "pre1",
            "f1",
            "b1",
            "b2",
            "b3",
            "s1",
            "s2",
            "h1",
            "post1",
        ]

    def test_the_rooms_two_top_voted_per_bucket_keep_theirs(self, comments):
        """Scores 50 and 40 keep a body in the Q1 bucket; 30 does not."""
        by_id = {row["comment_id"]: row for row in comments.rows(named=True)}
        assert by_id["r50"]["body"] == "wemby!"
        assert by_id["r40"]["body"] == "refs"
        assert by_id["r30"]["body"] is None

    def test_ties_break_by_comment_id(self, g7_periods, g7_clock):
        """Equal scores keep the lower ids, so the rule is deterministic."""
        t = g7_periods["start_wall"][0] // 120 * 120 + 240
        aligned = align_comments(
            _fact(
                [
                    _fact_row("c", t + 1, score=5, player=None, body="c"),
                    _fact_row("a", t + 2, score=5, player=None, body="a"),
                    _fact_row("b", t + 3, score=5, player=None, body="b"),
                ]
            ).with_columns(pl.lit(GAME).alias("game_id")),
            g7_periods,
            g7_clock,
        )
        comments = select_comments(aligned, CHET_NAME, _players())
        kept = comments.filter(pl.col("body").is_not_null())["comment_id"].to_list()
        assert sorted(kept) == ["a", "b"]

    def test_is_focus_is_attribution(self, comments):
        """A comment counts for him when attributed_player is him, no more."""
        by_id = {
            row["comment_id"]: row["is_focus"] for row in comments.rows(named=True)
        }
        assert by_id["f1"] is True
        assert by_id["r50"] is False
        assert by_id["r40"] is False

    def test_player_id_is_the_attributed_target(self, comments):
        """Every comment names who its sentiment is about, by the Player
        dimension's id; an unattributed comment names no one."""
        by_id = {
            row["comment_id"]: row["player_id"] for row in comments.rows(named=True)
        }
        assert by_id["f1"] == CHET
        assert by_id["r50"] == WEMBY
        assert by_id["r40"] is None

    def test_post_id_is_the_thread(self, comments):
        """The split thread's comment names the split thread."""
        by_id = {row["comment_id"]: row["post_id"] for row in comments.rows(named=True)}
        assert by_id["f1"] == SPLIT
        assert by_id["b1"] == LIVE


class TestPeriodCountsAndSwing:
    """The Player x Game x Period rollup and the index hook."""

    @pytest.fixture
    def aligned(self, g7_fact, g7_periods, g7_clock) -> pl.DataFrame:
        return align_comments(
            g7_fact.filter(pl.col("link_id") != PGT).with_columns(
                pl.lit(GAME).alias("game_id")
            ),
            g7_periods,
            g7_clock,
        )

    def test_counts_live_and_break_by_period_zero_filled(self, aligned):
        """Q1 has the split-thread comment; Q2 has the block, steal and
        halftime comments; Q3 and Q4 are zero; pre and post are out."""
        assert period_counts(aligned, CHET_NAME, 4) == {
            "1": {"neg": 1, "pos": 0, "neu": 0},
            "2": {"neg": 4, "pos": 2, "neu": 0},
            "3": {"neg": 0, "pos": 0, "neu": 0},
            "4": {"neg": 0, "pos": 0, "neu": 0},
        }

    def test_swing_is_last_minus_first_negative_share(self):
        """60 % negative in Q1 to 10 % in Q4 is a swing of -0.5; a period
        nobody spoke in is skipped, and one spoken period is no swing."""
        by_period = {
            "1": {"neg": 6, "pos": 2, "neu": 2},
            "2": {"neg": 0, "pos": 0, "neu": 0},
            "3": {"neg": 5, "pos": 5, "neu": 0},
            "4": {"neg": 1, "pos": 9, "neu": 0},
        }
        assert swing(by_period) == pytest.approx(-0.5)
        assert swing({"1": by_period["2"], "2": by_period["4"]}) == 0.0


class TestMeasureReactionLag:
    """How long the room takes to react, measured season-wide, never moved."""

    @pytest.fixture
    def measured(self, g7_fact, pbp_dir):
        return measure_reaction_lag(g7_fact, _posts(), _players(), pbp_dir)

    def _anchor(self, anchors: pl.DataFrame, action_number: int) -> dict:
        return anchors.filter(pl.col("action_number") == action_number).row(
            0, named=True
        )

    def _block_burst(self, bodies, player=CHET_NAME) -> pl.DataFrame:
        """Comments in the minute after the block, attributed to player."""
        minute = (_epoch(0, 58, 48) // 60 + 1) * 60
        return _fact(
            [
                _fact_row(f"x{i}", minute + 5 + i, body=body, player=player)
                for i, body in enumerate(bodies)
            ]
        )

    def test_pile_on_is_an_anchor_with_its_offset(self, measured):
        """Three comments naming the block in one minute: accepted, and the
        offset is the first of them minus the play's own stamp: 00:59:05
        against 00:58:48 is 17 seconds."""
        anchors, _ = measured
        block = self._anchor(anchors, 158)
        assert block["kind"] == "block"
        assert block["accepted"] is True
        assert block["reaction_n"] == 3
        assert block["wall_clock"] == _epoch(0, 58, 48)
        assert block["offset_seconds"] == 17

    def test_two_reactions_are_not_an_anchor(self, measured):
        """The steal drew two: counted, not accepted, no offset."""
        anchors, _ = measured
        steal = self._anchor(anchors, 210)
        assert steal["accepted"] is False
        assert steal["reaction_n"] == 2
        assert steal["offset_seconds"] is None

    def test_figures_summarize_the_accepted_offsets(self, measured):
        """Two candidates, one anchor in one game; its offset is every quantile."""
        anchors, figures = measured
        assert figures == {
            "candidates": 2,
            "anchors": 1,
            "games": 1,
            "median_offset_seconds": 17,
            "p25_offset_seconds": 17,
            "p75_offset_seconds": 17,
        }

    def test_the_vocabulary_names_a_play_without_its_word(self, pbp_dir):
        """'Swat', 'rejected' and 'denied' are how a block gets named."""
        fact = self._block_burst(["what a swat", "REJECTED", "denied!!"])

        anchors, _ = measure_reaction_lag(fact, _posts(), _players(), pbp_dir)

        assert self._anchor(anchors, 158)["accepted"] is True

    def test_reactions_count_for_the_plays_own_player(self, pbp_dir):
        """A burst about Wembanyama never anchors Holmgren's block."""
        fact = self._block_burst(
            ["block", "block", "block"], player="Victor Wembanyama"
        )

        anchors, _ = measure_reaction_lag(fact, _posts(), _players(), pbp_dir)

        assert self._anchor(anchors, 158)["reaction_n"] == 0

    def test_one_burst_counts_for_one_play(self, tmp_path):
        """Two blocks inside one window share a burst only once: it goes to
        the nearer play, and the other is left with nothing."""
        second = [
            _sas(
                174,
                period=2,
                clock="PT07M10.00S",
                time_actual=_stamp(0, 59, 50),
                action_type="2pt",
                sub_type="Layup",
                shot_result="Missed",
                person_id=CASTLE,
                block_person_id=CHET,
            ),
            _chet(
                175,
                period=2,
                clock="PT07M10.00S",
                time_actual=_stamp(0, 59, 50),
                action_type="block",
            ),
        ]
        _pbp([*G7_PLAYS, *second]).write_parquet(tmp_path / f"{GAME}.parquet")
        fact = self._block_burst(["block", "block", "block"])

        anchors, figures = measure_reaction_lag(fact, _posts(), _players(), tmp_path)

        assert self._anchor(anchors, 158)["accepted"] is True
        assert self._anchor(anchors, 175)["reaction_n"] == 0
        assert figures["anchors"] == 1

    def test_reaction_outside_the_window_is_ignored(self, pbp_dir):
        """Naming the block nine minutes later is not a reaction to it."""
        late = (_epoch(0, 58, 48) // 60 + 9) * 60
        fact = _fact([_fact_row(f"l{i}", late + i, body="block") for i in range(3)])

        anchors, _ = measure_reaction_lag(fact, _posts(), _players(), pbp_dir)

        assert self._anchor(anchors, 158)["accepted"] is False

    def test_made_dunk_is_a_candidate_by_sub_type(self, tmp_path):
        """A made 2pt whose sub_type is DUNK is looked for as a dunk; a
        missed one is not."""
        dunks = [
            _chet(
                9,
                clock="PT10M00.00S",
                time_actual=_stamp(0, 19, 0),
                action_type="2pt",
                sub_type="DUNK",
                shot_result="Made",
            ),
            _chet(
                10,
                clock="PT09M00.00S",
                time_actual=_stamp(0, 20, 0),
                action_type="2pt",
                sub_type="DUNK",
                shot_result="Missed",
            ),
        ]
        _pbp([*G7_MARKERS, *dunks]).write_parquet(tmp_path / f"{GAME}.parquet")

        anchors, _ = measure_reaction_lag(_fact([]), _posts(), _players(), tmp_path)

        assert anchors["kind"].to_list() == ["dunk"]
        assert anchors["action_number"].to_list() == [9]

    def test_a_game_without_a_clock_is_skipped(self, g7_fact, pbp_dir):
        """A threaded game with no banked feed adds nothing and fails nothing."""
        posts = pl.concat(
            [
                _posts(),
                _posts()
                .head(1)
                .with_columns(
                    pl.lit("t3_other").alias("post_id"), pl.lit(OTHER).alias("game_id")
                ),
            ]
        )

        _, figures = measure_reaction_lag(g7_fact, posts, _players(), pbp_dir)

        assert figures["candidates"] == 2
        assert figures["games"] == 1

    def test_nothing_accepted_has_no_offsets(self, pbp_dir):
        """Candidates without reactions: counted, with no quantiles."""
        _, figures = measure_reaction_lag(_fact([]), _posts(), _players(), pbp_dir)

        assert figures == {
            "candidates": 2,
            "anchors": 0,
            "games": 0,
            "median_offset_seconds": None,
            "p25_offset_seconds": None,
            "p75_offset_seconds": None,
        }

    def test_quantiles_are_observed_offsets(self):
        """Median and quartiles are offsets that happened, never interpolated;
        rejected candidates count as candidates only."""
        anchors = pl.DataFrame(
            {
                "game_id": ["a", "a", "b", "b", "c", "c"],
                "accepted": [True, True, True, True, True, False],
                "offset_seconds": [-100, -50, 10, 20, 200, None],
            },
            schema={
                "game_id": pl.String,
                "accepted": pl.Boolean,
                "offset_seconds": pl.Int64,
            },
        )

        assert reaction_lag_figures(anchors) == {
            "candidates": 6,
            "anchors": 5,
            "games": 3,
            "median_offset_seconds": 10,
            "p25_offset_seconds": -50,
            "p75_offset_seconds": 20,
        }


class TestResolveRecapSpecs:
    """Curation checked against the frames."""

    def test_resolves_identities_threads_room_and_path(self, pbp_dir):
        """A good entry gets its player, its live threads and its file."""
        [resolved] = resolve_recap_specs(
            [RecapSpec(GAME, "chet-holmgren")], _games(), _players(), _posts(), pbp_dir
        )
        assert resolved.attributed_player == CHET_NAME
        assert resolved.player_id == CHET
        assert set(resolved.thread_ids) == {LIVE, SPLIT}
        assert resolved.room_n == 47_000
        assert resolved.pbp_path == pbp_dir / f"{GAME}.parquet"
        assert resolved.key == f"{GAME}-chet-holmgren"

    def test_unknown_game_raises(self, pbp_dir):
        with pytest.raises(RecapError, match="0000000000 / chet-holmgren: game is not"):
            resolve_recap_specs(
                [RecapSpec("0000000000", "chet-holmgren")],
                _games(),
                _players(),
                _posts(),
                pbp_dir,
            )

    def test_unknown_slug_raises(self, pbp_dir):
        with pytest.raises(RecapError, match="slug is not in the Player dimension"):
            resolve_recap_specs(
                [RecapSpec(GAME, "nobody")], _games(), _players(), _posts(), pbp_dir
            )

    def test_game_without_a_live_thread_raises(self, pbp_dir):
        """Post-game threads alone are not a recap."""
        posts = _posts().filter(pl.col("post_type") != "game_thread")
        with pytest.raises(RecapError, match="no live game thread"):
            resolve_recap_specs(
                [RecapSpec(GAME, "chet-holmgren")], _games(), _players(), posts, pbp_dir
            )

    def test_unbanked_play_by_play_raises(self, tmp_path):
        with pytest.raises(RecapError, match="not banked"):
            resolve_recap_specs(
                [RecapSpec(GAME, "chet-holmgren")],
                _games(),
                _players(),
                _posts(),
                tmp_path,
            )


class TestBuildRecap:
    """One recap end to end."""

    def test_header_carries_identity_and_lineage(self, g7_doc):
        assert g7_doc.key == f"{GAME}-chet-holmgren"
        assert g7_doc.header == {
            "schema_version": SCHEMA_VERSION,
            "season": "2025-26",
            "generated_at": "2026-09-26T12:00:00+00:00",
            "game_id": GAME,
            "attributed_player": CHET_NAME,
            "player_id": CHET,
            "slug": "chet-holmgren",
            "config_versions": {"recaps": "1.0", "players": "4.6", "teams": "2.3"},
            "classifiers": {
                "sentiment": {
                    "model": "claude-haiku-4-5-20251001",
                    "prompt_version": "v2",
                }
            },
        }

    def test_header_stamps_the_sentiment_classifier_only(self, g7_fact, pbp_dir):
        """A recap reads the fact's sentiment, never the target verifier,
        so a verifier re-run does not read as a change to it."""
        target = {"model": "claude-sonnet-5", "prompt_version": "v1"}
        stamps = RecapStamps(
            season=STAMPS.season,
            generated_at=STAMPS.generated_at,
            config_versions=STAMPS.config_versions,
            classifiers={**STAMPS.classifiers, "target": target},
        )

        doc = build_recap(
            _spec(pbp_dir),
            fact=g7_fact,
            posts=_posts(),
            player_log=_g7_player_log(),
            team_log=G7_TEAM_LOG,
            players=_players(),
            pbp=_pbp(G7_PLAYS),
            stamps=stamps,
        )

        assert doc.header["classifiers"] == STAMPS.classifiers

    def test_frames_in_registry_order_and_valid(self, g7_doc):
        assert list(g7_doc.frames) == list(RECAP_FRAME_SCHEMAS)
        for name, schema in RECAP_FRAME_SCHEMAS.items():
            validate_schema(g7_doc.frames[name], schema, name)
            validate_nullability(
                g7_doc.frames[name], RECAP_NULLABLE_COLUMNS[name], name
            )

    def test_periods_carry_the_markers_stamps_to_the_second(self, g7_doc):
        periods = g7_doc.frames["periods"]
        assert periods["start_wall"].to_list() == [
            _epoch(0, 17),
            _epoch(0, 49),
            _epoch(1, 36),
            _epoch(2, 17),
        ]
        assert periods["end_action_number"][3] == 507

    def test_live_threads_only_merged(self, g7_doc):
        """Both game threads, never the post-game thread."""
        assert set(g7_doc.frames["comments"]["post_id"].to_list()) == {LIVE, SPLIT}
        threads = g7_doc.frames["threads"]
        assert threads["post_id"].to_list() == [LIVE, SPLIT]
        assert threads["comment_n"].to_list() == [11, 1]
        assert threads["is_primary"].to_list() == [True, False]

    def test_entry_is_the_rollup(self, g7_doc):
        entry = g7_doc.entry
        assert entry["file"] == f"recaps/{GAME}-chet-holmgren.json"
        assert entry["rows"] == g7_doc.frames["comments"].height == 12
        assert entry["live_n"] == 9
        assert entry["room_n"] == 47_000
        assert list(entry["by_period"]) == ["1", "2", "3", "4"]
        assert entry["by_period"]["2"] == {"neg": 4, "pos": 2, "neu": 0}
        assert entry["swing"] == pytest.approx(-1 / 3)
        assert entry["population"] == "live_thread"
        assert (
            entry["game_id"],
            entry["attributed_player"],
            entry["player_id"],
            entry["slug"],
        ) == (GAME, CHET_NAME, CHET, "chet-holmgren")

    def test_minutes_reconcile_against_the_box_score(self, g7_doc):
        """1,959 stint seconds round to 33 minutes, the box score's line."""
        seconds = stint_seconds(g7_doc.frames["stints"])
        assert seconds.filter(pl.col("person_id") == CHET)["seconds"].item() == 1959
        assert g7_doc.entry["minutes_diff"] == 0

    @pytest.mark.parametrize("minutes,warned", [(34, True), (33, False)])
    def test_stints_off_the_box_score_warn(
        self, g7_fact, pbp_dir, caplog, minutes, warned
    ):
        """33 stint minutes against a 34-minute line is logged as a warning
        naming him and the stat; an exact match is silent."""
        with caplog.at_level(logging.WARNING, logger="pipeline.recaps"):
            doc = build_recap(
                _spec(pbp_dir),
                fact=g7_fact,
                posts=_posts(),
                player_log=_g7_player_log(minutes),
                team_log=G7_TEAM_LOG,
                players=_players(),
                pbp=_pbp(G7_PLAYS),
                stamps=STAMPS,
            )

        named = [r.message for r in caplog.records if CHET_NAME in r.message]
        assert any("minutes 33" in m and "34" in m for m in named) is warned
        assert doc.entry["minutes_diff"] == 33 - minutes

    def test_a_line_off_the_box_score_warns(self, g7_fact, pbp_dir, caplog):
        """A box score crediting him a second block is named, stat and all;
        his other stats agree and stay silent."""
        line = _box_line(CHET, CHET_NAME, "OKC", **{**CHET_LINE, "blk": 2})

        with caplog.at_level(logging.WARNING, logger="pipeline.recaps"):
            build_recap(
                _spec(pbp_dir),
                fact=g7_fact,
                posts=_posts(),
                player_log=_player_log(line),
                team_log=G7_TEAM_LOG,
                players=_players(),
                pbp=_pbp(G7_PLAYS),
                stamps=STAMPS,
            )

        named = [r.message for r in caplog.records if CHET_NAME in r.message]
        assert len(named) == 1
        assert "blk 1" in named[0] and "2 in the box score" in named[0]

    def test_a_team_short_of_five_warns(self, g7_fact, pbp_dir, caplog):
        """The fixture logs a handful of players, so neither team reads five."""
        with caplog.at_level(logging.WARNING, logger="pipeline.recaps"):
            build_recap(
                _spec(pbp_dir),
                fact=g7_fact,
                posts=_posts(),
                player_log=_g7_player_log(),
                team_log=G7_TEAM_LOG,
                players=_players(),
                pbp=_pbp(G7_PLAYS),
                stamps=STAMPS,
            )

        assert any("on the floor" in r.message for r in caplog.records)

    def test_silent_focus_player_still_builds(self, g7_fact, pbp_dir):
        """A room that never mentions him: zero focus comments, no swing,
        every frame still valid."""
        fact = g7_fact.filter(
            (pl.col("attributed_player") != CHET_NAME).fill_null(True)
        )

        doc = build_recap(
            _spec(pbp_dir),
            fact=fact,
            posts=_posts(),
            player_log=_g7_player_log(),
            team_log=G7_TEAM_LOG,
            players=_players(),
            pbp=_pbp(G7_PLAYS),
            stamps=STAMPS,
        )

        for name, schema in RECAP_FRAME_SCHEMAS.items():
            validate_schema(doc.frames[name], schema, name)
            validate_nullability(doc.frames[name], RECAP_NULLABLE_COLUMNS[name], name)
        assert doc.entry["live_n"] == 0
        assert doc.entry["rows"] == doc.frames["comments"].height == 3
        assert doc.entry["swing"] == 0.0
        assert all(
            v == {"neg": 0, "pos": 0, "neu": 0} for v in doc.entry["by_period"].values()
        )

    def test_missing_box_score_line_raises(self, g7_fact, pbp_dir):
        with pytest.raises(RecapError, match="no box-score line"):
            build_recap(
                _spec(pbp_dir),
                fact=g7_fact,
                posts=_posts(),
                player_log=_g7_player_log().clear(),
                team_log=G7_TEAM_LOG,
                players=_players(),
                pbp=_pbp(G7_PLAYS),
                stamps=STAMPS,
            )


class TestSerializeAndWrite:
    """The file on disk."""

    def test_serialize_is_header_plus_column_arrays(self, g7_doc):
        data = serialize_recap(g7_doc)
        assert list(data) == ["header", "frames"]
        assert list(data["frames"]) == list(RECAP_FRAME_SCHEMAS)
        comments = data["frames"]["comments"]
        assert list(comments) == RECAP_COMMENTS_SCHEMA.names()
        assert len(comments["comment_id"]) == 12
        assert None in comments["body"]

    def test_write_lands_under_recaps_and_reports_bytes(self, g7_doc, tmp_path):
        path, size = write_recap(g7_doc, tmp_path)

        assert path == tmp_path / "recaps" / f"{GAME}-chet-holmgren.json"
        assert size == path.stat().st_size > 0
        assert not list(path.parent.glob("*.part"))
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == serialize_recap(g7_doc)


class TestScanCandidates:
    """The Player x Game x Period grain over every threaded game."""

    def test_ranks_pairs_by_swing_and_skips_unbanked_games(self, g7_fact, pbp_dir):
        """Chet over the threshold; Wembanyama below it; OTHER has a thread
        but no play-by-play, so it is skipped and counted."""
        posts = pl.concat(
            [
                _posts(),
                _posts()
                .head(1)
                .with_columns(
                    pl.lit("t3_other").alias("post_id"), pl.lit(OTHER).alias("game_id")
                ),
            ]
        )
        candidates, skipped = scan_candidates(
            g7_fact, posts, _games(), _players(), pbp_dir, min_live_n=3
        )

        assert skipped == [OTHER]
        assert candidates["attributed_player"].to_list() == [CHET_NAME]
        row = candidates.row(0, named=True)
        assert row["live_n"] == 7
        assert row["slug"] == "chet-holmgren"
        assert row["home_team"] == "Oklahoma City Thunder"
        assert row["swing"] == pytest.approx(-1 / 3)
        assert row["neg_shares"].startswith("p1:1.0;p2:0.667")
        assert row["curation"] == '- {game_id: "0042500317", slug: chet-holmgren}'

    def test_defective_markers_are_skipped_not_fatal(self, g7_fact, tmp_path, caplog):
        """A game whose markers fail to build is logged and skipped."""
        _pbp([m for m in G7_MARKERS if m["period"] != 2]).write_parquet(
            tmp_path / f"{GAME}.parquet"
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.recaps"):
            candidates, skipped = scan_candidates(
                g7_fact, _posts(), _games(), _players(), tmp_path
            )

        assert skipped == [GAME]
        assert candidates.is_empty()
        assert any("no clock for" in r.message for r in caplog.records)


class TestWriteRecaps:
    """The recaps directory holds exactly the curated set."""

    def test_writes_in_page_order_and_prunes_the_rest(self, g7_doc, tmp_path):
        """A file no longer curated is removed; other files are left alone."""
        recaps_dir = tmp_path / "recaps"
        recaps_dir.mkdir()
        stale = recaps_dir / "0022500001-kevin-durant.json"
        stale.write_text("{}")
        other = recaps_dir / "notes.txt"
        other.write_text("keep")

        written = write_recaps([g7_doc], tmp_path)

        assert written == [recaps_dir / f"{GAME}-chet-holmgren.json"]
        assert not stale.exists()
        assert other.exists()
        assert sorted(p.name for p in recaps_dir.glob("*.json")) == [
            f"{GAME}-chet-holmgren.json"
        ]

    def test_nothing_curated_leaves_no_directory(self, tmp_path):
        """A season without recaps writes nothing and creates nothing."""
        assert write_recaps([], tmp_path) == []
        assert not (tmp_path / "recaps").exists()
