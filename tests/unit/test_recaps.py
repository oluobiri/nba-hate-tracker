"""
Tests for pipeline/recaps.py: the shared clock and what sits on it.

Frames are built locally: an action row in PLAY_BY_PLAY_SCHEMA's shape,
period markers with the archive's "(8:17 PM EST)" description, and a
comment row with the columns the alignment needs. Wall-clock expectations
are derived with zoneinfo in the test, never from the code under test.
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
    Focus,
    RecapError,
    RecapStamps,
    ResolvedSpec,
    align_comments,
    build_periods,
    build_recap,
    build_stints,
    derive_kind,
    error_seconds,
    fill_scores,
    focus_identity,
    measure_anchors,
    pair_blocks,
    parse_clock_seconds,
    parse_running_totals,
    period_counts,
    place_plays,
    resolve_recap_specs,
    scan_candidates,
    select_comments,
    serialize_recap,
    slice_plays,
    stint_minutes,
    swing,
    write_recap,
    write_recaps,
)
from pipeline.schemas import (
    PLAY_BY_PLAY_SCHEMA,
    RECAP_ANCHORS_SCHEMA,
    RECAP_COMMENTS_SCHEMA,
    RECAP_FRAME_SCHEMAS,
    RECAP_NULLABLE_COLUMNS,
    RECAP_PLAYS_SCHEMA,
    RECAP_STINTS_SCHEMA,
    SCHEMA_VERSION,
    validate_nullability,
    validate_schema,
)
from utils.recaps_config import RecapSpec

GAME = "0042500317"
OTHER = "0022500001"
NY = ZoneInfo("America/New_York")


def _action(**overrides) -> dict:
    """One archive row, snake_cased as PLAY_BY_PLAY_SCHEMA holds it."""
    row = {
        "game_id": GAME,
        "action_number": 4,
        "clock": "PT12M00.00S",
        "period": 1,
        "team_id": 0,
        "team_tricode": "",
        "person_id": 0,
        "player_name": "",
        "player_name_i": "",
        "x_legacy": 0,
        "y_legacy": 0,
        "shot_distance": 0,
        "shot_result": "",
        "is_field_goal": 0,
        "score_home": "",
        "score_away": "",
        "points_total": 0,
        "location": "",
        "description": "",
        "action_type": "",
        "sub_type": "",
        "video_available": 0,
        "shot_value": 0,
        "action_id": 1,
    }
    row.update(overrides)
    return row


def _pbp(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=PLAY_BY_PLAY_SCHEMA)


def _marker(period: int, sub_type: str, hhmm: str, action_id: int, **over) -> dict:
    """A period marker: 'Start of 1st Period (8:17 PM EST)' style."""
    ordinal = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(period, f"{period}th")
    word = "Start" if sub_type == "start" else "End"
    return _action(
        period=period,
        action_type="period",
        sub_type=sub_type,
        description=f"{word} of {ordinal} Period ({hhmm} EST)",
        action_id=action_id,
        clock="PT12M00.00S" if sub_type == "start" else "PT00M00.00S",
        **over,
    )


def _dates(*pairs: tuple[str, date]) -> pl.DataFrame:
    return pl.DataFrame(
        {"game_id": [g for g, _ in pairs], "game_date": [d for _, d in pairs]},
        schema={"game_id": pl.String, "game_date": pl.Date},
    )


def _epoch(day: date, hour: int, minute: int, days: int = 0) -> int:
    """Epoch seconds of an Eastern wall-clock time, DST from the zone."""
    local = datetime(day.year, day.month, day.day + days, hour, minute, tzinfo=NY)
    return int(local.timestamp())


JUNE = date(2026, 6, 1)
JANUARY = date(2026, 1, 15)

# WCF G7's eight markers, as the archive carries them
G7_MARKERS = [
    _marker(1, "start", "8:17 PM", 1),
    _marker(1, "end", "8:46 PM", 121),
    _marker(2, "start", "8:49 PM", 122),
    _marker(2, "end", "9:19 PM", 250),
    _marker(3, "start", "9:36 PM", 251),
    _marker(3, "end", "10:13 PM", 392),
    _marker(4, "start", "10:17 PM", 393),
    _marker(4, "end", "10:49 PM", 507),
]


@pytest.fixture
def g7_periods() -> pl.DataFrame:
    """The G7 clock on a June date."""
    return build_periods(_pbp(G7_MARKERS), _dates((GAME, JUNE)))


class TestParseClock:
    """The archive's ISO-style clock to seconds remaining."""

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


class TestBuildPeriods:
    """The game clock from the period markers."""

    def test_columns_and_order(self, g7_periods):
        """game_id, then the period columns, one row per period in order."""
        assert g7_periods.columns == ["game_id", *PERIOD_COLUMNS]
        assert g7_periods["period"].to_list() == [1, 2, 3, 4]
        assert g7_periods["start_seconds"].to_list() == [0, 720, 1440, 2160]
        assert g7_periods["end_seconds"].to_list() == [720, 1440, 2160, 2880]
        assert g7_periods["start_action_id"].to_list() == [1, 122, 251, 393]
        assert g7_periods["end_action_id"].to_list() == [121, 250, 392, 507]

    def test_est_label_in_daylight_time_is_eastern_local(self, g7_periods):
        """The label reads EST in June; the time is Eastern local, so the
        zone's daylight offset applies."""
        assert g7_periods["start_wall"][0] == _epoch(JUNE, 20, 17)
        assert g7_periods["end_wall"][3] == _epoch(JUNE, 22, 49)
        # EDT is UTC-4: 8:17 PM is 00:17 UTC the next day
        assert g7_periods["start_wall"][0] == int(
            datetime(2026, 6, 2, 0, 17, tzinfo=ZoneInfo("UTC")).timestamp()
        )

    def test_standard_time_uses_the_winter_offset(self):
        """The same label in January is an hour further from UTC."""
        periods = build_periods(_pbp(G7_MARKERS), _dates((GAME, JANUARY)))

        assert periods["start_wall"][0] == _epoch(JANUARY, 20, 17)
        assert periods["start_wall"][0] == int(
            datetime(2026, 1, 16, 1, 17, tzinfo=ZoneInfo("UTC")).timestamp()
        )

    def test_west_coast_venue_crosses_midnight_eastern(self):
        """A late tip ends after midnight Eastern: the buzzer rolls to the
        next day, once, and stays there."""
        markers = [
            _marker(1, "start", "10:40 PM", 1),
            _marker(1, "end", "11:10 PM", 50),
            _marker(2, "start", "11:12 PM", 51),
            _marker(2, "end", "11:42 PM", 100),
            _marker(3, "start", "12:01 AM", 101),
            _marker(3, "end", "12:31 AM", 150),
            _marker(4, "start", "12:34 AM", 151),
            _marker(4, "end", "1:05 AM", 200),
        ]

        periods = build_periods(_pbp(markers), _dates((GAME, JUNE)))

        assert periods["start_wall"][0] == _epoch(JUNE, 22, 40)
        assert periods["start_wall"][2] == _epoch(JUNE, 0, 1, days=1)
        assert periods["end_wall"][3] == _epoch(JUNE, 1, 5, days=1)
        assert periods["end_wall"].is_sorted()

    def test_overtime_periods_are_five_minutes(self):
        """Period 5 adds 300 seconds after regulation's 2,880."""
        markers = [
            *G7_MARKERS,
            _marker(5, "start", "10:52 PM", 508),
            _marker(5, "end", "11:05 PM", 560),
        ]

        periods = build_periods(_pbp(markers), _dates((GAME, JUNE)))

        assert periods["start_seconds"][4] == 2880
        assert periods["end_seconds"][4] == 3180

    def test_vectorized_over_two_games(self):
        """Two games' markers in one frame give two clocks, each on its own date."""
        other = [
            _marker(1, "start", "7:10 PM", 1, game_id=OTHER),
            _marker(1, "end", "7:40 PM", 60, game_id=OTHER),
        ]

        periods = build_periods(
            _pbp([*G7_MARKERS, *other]), _dates((GAME, JUNE), (OTHER, JANUARY))
        )

        assert periods["game_id"].to_list() == [OTHER] + [GAME] * 4
        assert periods.filter(pl.col("game_id") == OTHER)["start_wall"][0] == _epoch(
            JANUARY, 19, 10
        )

    def test_missing_end_marker_raises(self):
        """A period with a start and no end names the game and the period."""
        markers = [
            m for m in G7_MARKERS if not (m["period"] == 2 and m["sub_type"] == "end")
        ]

        with pytest.raises(RecapError, match=f"{GAME}: period 2 has no end marker"):
            build_periods(_pbp(markers), _dates((GAME, JUNE)))

    def test_repeated_start_marker_raises(self):
        """Two starts for one period is an archive defect, not a choice."""
        markers = [*G7_MARKERS, _marker(3, "start", "9:37 PM", 252)]

        with pytest.raises(RecapError, match="period 3 has 2 start markers"):
            build_periods(_pbp(markers), _dates((GAME, JUNE)))

    def test_marker_without_a_wall_clock_raises(self):
        """A marker whose description carries no time names its action."""
        markers = [*G7_MARKERS]
        markers[2] = _action(
            period=2,
            action_type="period",
            sub_type="start",
            description="Start of 2nd Period",
            action_id=122,
        )

        with pytest.raises(RecapError, match="without a wall clock at action 122"):
            build_periods(_pbp(markers), _dates((GAME, JUNE)))

    def test_period_ending_before_it_starts_raises(self):
        """A period whose end precedes its start cannot carry a line."""
        markers = [*G7_MARKERS]
        markers[3] = _marker(2, "end", "8:40 PM", 250)

        with pytest.raises(RecapError, match="period 2 ends at or before it starts"):
            build_periods(_pbp(markers), _dates((GAME, JUNE)))

    def test_non_contiguous_periods_raise(self):
        """Periods 1, 2, 4 with no 3: the clock cannot accumulate."""
        markers = [m for m in G7_MARKERS if m["period"] != 3]

        with pytest.raises(RecapError, match="not contiguous"):
            build_periods(_pbp(markers), _dates((GAME, JUNE)))

    def test_overlapping_periods_raise(self):
        """A period that starts before the previous one ended."""
        markers = [*G7_MARKERS]
        markers[4] = _marker(3, "start", "9:15 PM", 251)

        with pytest.raises(RecapError, match="period 3 starts before period 2 ends"):
            build_periods(_pbp(markers), _dates((GAME, JUNE)))

    def test_missing_game_date_raises(self):
        """A game the dimension does not date cannot be placed on a day."""
        with pytest.raises(RecapError, match=GAME):
            build_periods(_pbp(G7_MARKERS), _dates((OTHER, JUNE)))


def _comments(*created: int, game_id: str = GAME) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "comment_id": [f"c{i}" for i in range(len(created))],
            "game_id": [game_id] * len(created),
            "created_utc": list(created),
        },
        schema={"comment_id": pl.String, "game_id": pl.String, "created_utc": pl.Int64},
    )


class TestAlignComments:
    """Wall clock back to game seconds, with a phase."""

    def test_straight_line_within_a_period(self, g7_periods):
        """Halfway through Q1's 29 wall minutes is halfway through its 720 seconds."""
        start, end = g7_periods["start_wall"][0], g7_periods["end_wall"][0]

        aligned = align_comments(_comments(start, (start + end) // 2, end), g7_periods)

        assert aligned["phase"].to_list() == ["live"] * 3
        assert aligned["game_seconds"].to_list() == [0, 360, 720]
        assert aligned["period"].to_list() == [1, 1, 1]

    def test_break_pins_to_the_period_just_played(self, g7_periods):
        """A halftime comment sits at the end of Q2, period 2."""
        halftime = g7_periods["end_wall"][1] + 300

        aligned = align_comments(_comments(halftime), g7_periods)

        assert aligned.row(0, named=True) | {} == {
            "comment_id": "c0",
            "game_id": GAME,
            "created_utc": halftime,
            "phase": "break",
            "game_seconds": 1440,
            "period": 2,
        }

    def test_before_tip_off_is_pre_at_zero(self, g7_periods):
        """Pre-game chatter keeps its timestamp and sits at second 0."""
        aligned = align_comments(_comments(g7_periods["start_wall"][0] - 1), g7_periods)

        assert aligned["phase"][0] == "pre"
        assert aligned["game_seconds"][0] == 0
        assert aligned["period"][0] is None

    def test_after_the_buzzer_is_post_at_the_end(self, g7_periods):
        """Post-game chatter sits at the game's last second, no period."""
        aligned = align_comments(_comments(g7_periods["end_wall"][3] + 1), g7_periods)

        assert aligned["phase"][0] == "post"
        assert aligned["game_seconds"][0] == 2880
        assert aligned["period"][0] is None

    def test_row_order_and_columns_are_kept(self, g7_periods):
        """Input order survives; the three placement columns are appended."""
        later, earlier = g7_periods["start_wall"][2] + 60, g7_periods["start_wall"][0]

        aligned = align_comments(_comments(later, earlier), g7_periods)

        assert aligned["comment_id"].to_list() == ["c0", "c1"]
        assert aligned.columns == [
            "comment_id",
            "game_id",
            "created_utc",
            "game_seconds",
            "phase",
            "period",
        ]

    def test_two_games_align_on_their_own_clocks(self):
        """A comment maps through its own game's markers."""
        other = [
            _marker(1, "start", "7:10 PM", 1, game_id=OTHER),
            _marker(1, "end", "7:40 PM", 60, game_id=OTHER),
        ]
        periods = build_periods(
            _pbp([*G7_MARKERS, *other]), _dates((GAME, JUNE), (OTHER, JANUARY))
        )
        other_start = periods.filter(pl.col("game_id") == OTHER)["start_wall"][0]
        comments = pl.concat(
            [_comments(other_start + 900, game_id=OTHER), _comments(other_start + 900)]
        )

        aligned = align_comments(comments, periods)

        assert aligned["phase"].to_list() == ["live", "pre"]
        assert aligned["game_seconds"].to_list() == [360, 0]


class TestPlacePlays:
    """Game seconds from the period clock, wall clock by the line."""

    def test_game_seconds_and_wall_clock(self, g7_periods):
        """Six minutes left in Q2 is second 1,080, halfway along Q2's line."""
        plays = _pbp([_action(period=2, clock="PT06M00.00S", action_id=200)])
        start, end = g7_periods["start_wall"][1], g7_periods["end_wall"][1]

        placed = place_plays(plays, g7_periods)

        assert placed["game_seconds"][0] == 1080
        assert placed["wall_clock"][0] == start + round((end - start) / 2)
        assert placed.columns == [
            *PLAY_BY_PLAY_SCHEMA.names(),
            "game_seconds",
            "wall_clock",
        ]

    def test_period_ends_land_on_the_markers(self, g7_periods):
        """The first and last second of a period map to its markers exactly."""
        plays = _pbp(
            [
                _action(period=3, clock="PT12M00.00S", action_id=251),
                _action(period=3, clock="PT00M00.00S", action_id=392),
            ]
        )

        placed = place_plays(plays, g7_periods)

        assert placed["game_seconds"].to_list() == [1440, 2160]
        assert placed["wall_clock"].to_list() == [
            g7_periods["start_wall"][2],
            g7_periods["end_wall"][2],
        ]

    def test_tenths_round_to_the_second(self, g7_periods):
        """PT00M40.20S in Q1 is second 680, not a float."""
        placed = place_plays(_pbp([_action(clock="PT00M40.20S")]), g7_periods)

        assert placed["game_seconds"][0] == 680
        assert placed["game_seconds"].dtype == pl.Int64

    def test_play_in_an_unmarked_period_raises(self, g7_periods):
        """A period the markers do not cover has no line to place on."""
        plays = _pbp([_action(period=5, clock="PT04M00.00S", action_id=600)])

        with pytest.raises(RecapError, match="period 5 has no markers"):
            place_plays(plays, g7_periods)

    def test_malformed_clock_raises(self, g7_periods):
        """A clock that does not parse names its action."""
        plays = _pbp([_action(clock="6:00", action_id=77)])

        with pytest.raises(RecapError, match="'6:00' does not parse"):
            place_plays(plays, g7_periods)


# --- Plays and stints -------------------------------------------------------

OKC, SAS = 1610612760, 1610612759
CHET = 1631096
CHET_FOCUS = Focus(CHET, "Holmgren", OKC)


def _okc(**over) -> dict:
    return _action(team_id=OKC, team_tricode="OKC", **over)


def _sas(**over) -> dict:
    return _action(team_id=SAS, team_tricode="SAS", **over)


def _chet(**over) -> dict:
    return _okc(
        person_id=CHET, player_name="Holmgren", player_name_i="C. Holmgren", **over
    )


# A G7-shaped game: the eight markers plus the plays the rules turn on.
G7_PLAYS = [
    G7_MARKERS[0],
    _chet(
        action_id=2,
        action_number=4,
        action_type="Jump Ball",
        description="Jump Ball Holmgren vs. Wembanyama: Tip to Castle",
    ),
    _chet(
        action_id=8,
        action_number=14,
        clock="PT10M41.00S",
        action_type="Made Shot",
        sub_type="Step Back Jump shot",
        shot_result="Made",
        is_field_goal=1,
        shot_value=2,
        x_legacy=118,
        y_legacy=0,
        shot_distance=12,
        score_home="2",
        score_away="4",
        description="Holmgren 12' Step Back Jump Shot (2 PTS) (Wallace 1 AST)",
    ),
    _chet(
        action_id=12,
        action_number=21,
        clock="PT09M39.00S",
        action_type="Missed Shot",
        sub_type="Driving Floating Jump Shot",
        shot_result="Missed",
        is_field_goal=1,
        shot_value=2,
        x_legacy=-61,
        y_legacy=57,
        shot_distance=8,
        description="MISS Holmgren 8' Driving Floating Jump Shot",
    ),
    _chet(
        action_id=41,
        action_number=58,
        clock="PT06M33.00S",
        action_type="Substitution",
        description="SUB: McCain FOR Holmgren",
    ),
    _okc(
        action_id=62,
        action_number=87,
        clock="PT04M24.00S",
        action_type="Substitution",
        person_id=1641717,
        player_name="Wallace",
        player_name_i="C. Wallace",
        description="SUB: Holmgren FOR Wallace",
    ),
    _sas(
        action_id=63,
        action_number=88,
        clock="PT04M24.00S",
        action_type="Substitution",
        person_id=1627936,
        player_name="Vassell",
        player_name_i="D. Vassell",
        description="SUB: Holmgren FOR Vassell",
    ),
    _chet(
        action_id=100,
        action_number=136,
        clock="PT01M12.00S",
        action_type="Substitution",
        description="SUB: Hartenstein FOR Holmgren",
    ),
    G7_MARKERS[1],
    G7_MARKERS[2],
    _okc(
        action_id=128,
        action_number=180,
        period=2,
        clock="PT11M07.00S",
        action_type="Substitution",
        person_id=1628983,
        player_name="Gilgeous-Alexander",
        player_name_i="S. Gilgeous-Alexander",
        description="SUB: Holmgren FOR Gilgeous-Alexander",
    ),
    _sas(
        action_id=157,
        action_number=220,
        period=2,
        clock="PT07M40.00S",
        action_type="Missed Shot",
        sub_type="Driving Dunk Shot",
        shot_result="Missed",
        is_field_goal=1,
        shot_value=2,
        x_legacy=-5,
        y_legacy=10,
        shot_distance=2,
        person_id=1642844,
        player_name="Harper",
        player_name_i="D. Harper",
        description="MISS Harper 2' Driving Dunk",
    ),
    _chet(
        action_id=158,
        action_number=220,
        period=2,
        clock="PT07M40.00S",
        description="Holmgren BLOCK (1 BLK)",
    ),
    _chet(
        action_id=170,
        action_number=237,
        period=2,
        clock="PT07M02.00S",
        action_type="Foul",
        sub_type="Shooting",
        description="Holmgren S.FOUL (P1.T2) (J.Tiven)",
    ),
    _chet(
        action_id=178,
        action_number=249,
        period=2,
        clock="PT06M30.00S",
        action_type="Rebound",
        sub_type="Unknown",
        description="Holmgren REBOUND (Off:1 Def:1)",
    ),
    _chet(
        action_id=187,
        action_number=263,
        period=2,
        clock="PT05M30.00S",
        action_type="Free Throw",
        sub_type="Free Throw 1 of 2",
        description="MISS Holmgren Free Throw 1 of 2",
    ),
    _chet(
        action_id=188,
        action_number=264,
        period=2,
        clock="PT05M30.00S",
        action_type="Free Throw",
        sub_type="Free Throw 2 of 2",
        score_home="30",
        score_away="35",
        description="Holmgren Free Throw 2 of 2 (3 PTS)",
    ),
    _sas(
        action_id=190,
        action_number=270,
        period=2,
        clock="PT05M10.00S",
        action_type="Free Throw",
        sub_type="Free Throw 1 of 1",
        person_id=1641705,
        player_name="Wembanyama",
        player_name_i="V. Wembanyama",
        score_home="30",
        score_away="36",
        description="Wembanyama Free Throw 1 of 1 (10 PTS)",
    ),
    _okc(
        action_id=195,
        action_number=280,
        period=2,
        clock="PT04M50.00S",
        action_type="Made Shot",
        sub_type="Layup Shot",
        shot_result="Made",
        is_field_goal=1,
        shot_value=2,
        x_legacy=10,
        y_legacy=15,
        shot_distance=3,
        person_id=1641717,
        player_name="Wallace",
        player_name_i="C. Wallace",
        score_home="32",
        score_away="36",
        description="Wallace 3' Layup Shot (4 PTS) (Holmgren 1 AST)",
    ),
    _chet(
        action_id=200,
        action_number=290,
        period=2,
        clock="PT04M00.00S",
        action_type="Turnover",
        sub_type="Lost Ball",
        description="Holmgren Lost Ball Turnover (P1.T3)",
    ),
    _sas(
        action_id=209,
        action_number=300,
        period=2,
        clock="PT03M20.00S",
        action_type="Turnover",
        sub_type="Bad Pass",
        person_id=1642264,
        player_name="Castle",
        player_name_i="S. Castle",
        description="Castle Bad Pass Turnover (P1.T4)",
    ),
    _chet(
        action_id=210,
        action_number=300,
        period=2,
        clock="PT03M20.00S",
        description="Holmgren STEAL (1 STL)",
    ),
    _action(
        action_id=230,
        action_number=320,
        period=2,
        clock="PT02M00.00S",
        action_type="Timeout",
        sub_type="Regular",
        person_id=SAS,
        description="Spurs Timeout: Regular (Reg.2 Short 0)",
    ),
    G7_MARKERS[3],
    G7_MARKERS[4],
    _chet(
        action_id=312,
        action_number=439,
        period=3,
        clock="PT05M00.00S",
        action_type="Rebound",
        sub_type="Unknown",
        description="Holmgren REBOUND (Off:1 Def:2)",
    ),
    G7_MARKERS[5],
    G7_MARKERS[6],
    G7_MARKERS[7],
]


@pytest.fixture
def g7_game() -> pl.DataFrame:
    return _pbp(G7_PLAYS)


@pytest.fixture
def g7_plays(g7_game, g7_periods) -> pl.DataFrame:
    return slice_plays(g7_game, g7_periods, CHET_FOCUS)


def _by_action(frame: pl.DataFrame, action_id: int) -> dict:
    return frame.filter(pl.col("action_id") == action_id).row(0, named=True)


class TestFocusIdentity:
    """The focus player as the archive names him."""

    def test_name_and_team_from_his_rows(self, g7_game):
        """The surname the descriptions use, and the team his rows carry."""
        assert focus_identity(g7_game, CHET) == CHET_FOCUS

    def test_no_action_raises(self, g7_game):
        """A player with no row in the game cannot anchor a recap."""
        with pytest.raises(RecapError, match=f"{GAME}: player 999 has no action"):
            focus_identity(g7_game, 999)


class TestFillScores:
    """The running score on every row."""

    def test_carries_the_score_across_rows_that_do_not_change_it(self, g7_game):
        """A missed free throw and a rebound read the last score written."""
        filled = fill_scores(g7_game)

        assert _by_action(filled, 187)["score_home"] == 2
        assert _by_action(filled, 187)["score_away"] == 4
        assert _by_action(filled, 200)["score_away"] == 36

    def test_zero_before_the_first_score(self, g7_game):
        """Tip-off is 0-0, not null."""
        filled = fill_scores(g7_game)

        assert _by_action(filled, 2)["score_home"] == 0
        assert filled["score_home"].dtype == pl.Int64
        assert filled["score_home"].null_count() == 0

    def test_sorted_by_action(self, g7_game):
        """The fill runs in action order whatever order the rows arrive in."""
        filled = fill_scores(g7_game.sample(fraction=1.0, shuffle=True, seed=1))

        assert filled["action_id"].is_sorted()
        assert _by_action(filled, 195)["score_home"] == 32


class TestDeriveKind:
    """Every play's kind, and whose play it is."""

    @pytest.fixture
    def kinds(self, g7_game) -> pl.DataFrame:
        return derive_kind(g7_game, CHET_FOCUS)

    @pytest.mark.parametrize(
        "action_id,kind",
        [
            (1, "period_start"),
            (121, "period_end"),
            (158, "block"),
            (210, "steal"),
            (41, "sub_out"),
            (62, "sub_in"),
            (128, "sub_in"),
            (8, "shot"),
            (157, "shot"),
            (188, "free_throw"),
            (178, "rebound"),
            (200, "turnover"),
            (170, "foul"),
            (230, "timeout"),
            (2, "jump_ball"),
        ],
    )
    def test_kind(self, kinds, action_id, kind):
        """Blank types read from the description; the rest from action_type."""
        assert _by_action(kinds, action_id)["kind"] == kind

    def test_same_surname_on_the_other_bench_is_not_a_check_in(self, kinds):
        """SUB: Holmgren FOR Vassell on the Spurs' side is someone else."""
        assert _by_action(kinds, 63)["kind"] == "other"
        assert _by_action(kinds, 63)["is_focus"] is False

    def test_is_focus_covers_his_rows_check_ins_and_assists(self, kinds):
        """His own rows, the substitutions that bring him on, and the
        teammate's made shot that credits him."""
        assert _by_action(kinds, 8)["is_focus"] is True
        assert _by_action(kinds, 62)["is_focus"] is True
        assert _by_action(kinds, 195)["is_focus"] is True
        assert _by_action(kinds, 157)["is_focus"] is False
        assert _by_action(kinds, 190)["is_focus"] is False


class TestPairBlocks:
    """A block or steal points at the play it ended."""

    @pytest.fixture
    def paired(self, g7_game) -> pl.DataFrame:
        return pair_blocks(derive_kind(g7_game, CHET_FOCUS))

    def test_block_takes_the_shots_id_and_location(self, paired):
        """The block draws where Harper's dunk was attempted."""
        block = _by_action(paired, 158)
        assert block["paired_action_id"] == 157
        assert (block["x_legacy"], block["y_legacy"], block["shot_distance"]) == (
            -5,
            10,
            2,
        )

    def test_steal_takes_the_turnovers_id_only(self, paired):
        """A turnover has no location to borrow."""
        steal = _by_action(paired, 210)
        assert steal["paired_action_id"] == 209
        assert (steal["x_legacy"], steal["y_legacy"]) == (0, 0)

    def test_other_rows_are_unpaired_and_untouched(self, paired):
        """A shot keeps its own coordinates and pairs with nothing."""
        shot = _by_action(paired, 8)
        assert shot["paired_action_id"] is None
        assert shot["x_legacy"] == 118
        assert paired.height == len(G7_PLAYS)

    def test_unpaired_block_raises(self, g7_game):
        """A block whose number no play shares is an archive defect."""
        orphan = g7_game.filter(pl.col("action_id") != 157)

        with pytest.raises(RecapError, match="block at action 158"):
            pair_blocks(derive_kind(orphan, CHET_FOCUS))


class TestParseRunningTotals:
    """The focus player's line, read off his descriptions."""

    @pytest.mark.parametrize(
        "action_id,column,value",
        [
            (8, "pts", 2),
            (188, "pts", 3),
            (178, "reb", 2),
            (158, "blk", 1),
            (210, "stl", 1),
            (170, "pf", 1),
            (200, "tov", 1),
            (195, "ast", 1),
        ],
    )
    def test_reads_each_total(self, g7_plays, action_id, column, value):
        """Each parenthesis pattern lands in its column on the row that carries it."""
        assert _by_action(g7_plays, action_id)[column] == value

    def test_carries_forward_over_his_rows_only(self, g7_plays):
        """His steal still shows 3 points and the assist; the timeout after it
        shows nothing, and so does the jump ball before any total."""
        steal = _by_action(g7_plays, 210)
        assert (steal["pts"], steal["ast"], steal["blk"]) == (3, 1, 1)
        timeout = _by_action(g7_plays, 230)
        assert all(
            timeout[c] is None for c in ("pts", "reb", "ast", "blk", "stl", "tov", "pf")
        )
        assert _by_action(g7_plays, 2)["pts"] is None

    def test_a_teammates_points_are_not_his(self, g7_plays):
        """Wallace's (4 PTS) on the assist row does not become Holmgren's."""
        assert _by_action(g7_plays, 195)["pts"] == 3

    def test_ast_only_under_his_name(self, g7_game, g7_periods):
        """(Wallace 1 AST) on his own shot is Wallace's assist, not his."""
        plays = parse_running_totals(
            place_plays(derive_kind(fill_scores(g7_game), CHET_FOCUS), g7_periods),
            CHET_FOCUS,
        )
        assert _by_action(plays, 8)["ast"] is None


class TestSlicePlays:
    """What a recap ships, in the contract's shape."""

    def test_conforms_to_the_plays_frame(self, g7_plays):
        """Column names, dtypes, order and nullability are the contract's."""
        validate_schema(g7_plays.drop("game_id"), RECAP_PLAYS_SCHEMA, "plays")
        validate_nullability(
            g7_plays.drop("game_id"), RECAP_NULLABLE_COLUMNS["plays"], "plays"
        )
        assert g7_plays["action_id"].is_sorted()

    def test_keeps_his_plays_both_teams_shots_markers_and_timeouts(self, g7_plays):
        """Check-ins and the assist row count as his; Harper's miss is a shot."""
        kept = set(g7_plays["action_id"].to_list())
        assert {
            2,
            8,
            12,
            41,
            62,
            100,
            128,
            157,
            158,
            170,
            178,
            187,
            188,
            195,
            200,
            210,
            230,
            312,
        } <= kept
        assert {1, 121, 122, 250, 251, 392, 393, 507} <= kept

    def test_drops_other_players_free_throws_turnovers_and_subs(self, g7_plays):
        """Wembanyama's free throw, Castle's turnover and the Spurs' sub are not drawn."""
        kept = set(g7_plays["action_id"].to_list())
        assert not {190, 209, 63} & kept

    def test_score_carries_the_dropped_free_throw(self, g7_plays):
        """The assist row after Wembanyama's free throw reads 32-36, not 32-35."""
        assert _by_action(g7_plays, 195)["score_away"] == 36
        assert _by_action(g7_plays, 200)["score_away"] == 36

    def test_made_is_null_off_a_shot(self, g7_plays):
        """True, False, or null when nothing was shot."""
        assert _by_action(g7_plays, 8)["made"] is True
        assert _by_action(g7_plays, 157)["made"] is False
        assert _by_action(g7_plays, 178)["made"] is None

    def test_both_clocks(self, g7_plays, g7_periods):
        """The block sits at Q2 4:20 elapsed, on Q2's line."""
        block = _by_action(g7_plays, 158)
        assert block["game_seconds"] == 720 + 260
        start, end = g7_periods["start_wall"][1], g7_periods["end_wall"][1]
        assert block["wall_clock"] == start + round((end - start) * 260 / 720)


class TestBuildStints:
    """On-court intervals from the substitutions and the period openings."""

    def test_stints(self, g7_plays, g7_periods):
        """Started Q1 and left at 6:33 (first sub takes him off), back at 4:24 to 1:12; Q2 from
        11:07 to the buzzer; all of Q3 on a rebound alone; none of Q4."""
        stints = build_stints(g7_plays, g7_periods)

        assert stints.schema == RECAP_STINTS_SCHEMA
        assert stints.rows() == [
            (1, 0, 327),
            (1, 456, 648),
            (2, 773, 1440),
            (3, 1440, 2160),
        ]


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
            "game_date": [JUNE, JANUARY],
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
            "player_id": [CHET, 1641705],
        },
        schema={
            "attributed_player": pl.String,
            "slug": pl.String,
            "player_id": pl.Int64,
        },
    )


def _player_games(minutes: int = 33) -> pl.DataFrame:
    return pl.DataFrame(
        {"game_id": [GAME], "attributed_player": [CHET_NAME], "minutes": [minutes]},
        schema={
            "game_id": pl.String,
            "attributed_player": pl.String,
            "minutes": pl.Int64,
        },
    )


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
def g7_fact(g7_periods, g7_plays) -> pl.DataFrame:
    """Comments around the G7 clock: a Q1 bucket of room noise, a block
    pile-on, a steal with two reactions, halftime, pre and post chatter."""
    q1 = g7_periods["start_wall"][0]
    bucket = (q1 + 600) // 120 * 120
    block_wall = _by_action(g7_plays, 158)["wall_clock"]
    minute = (block_wall // 60 + 1) * 60
    steal_wall = _by_action(g7_plays, 210)["wall_clock"]
    steal_minute = (steal_wall // 60 + 1) * 60
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
def pbp_dir(tmp_path, g7_game) -> Path:
    g7_game.write_parquet(tmp_path / f"{GAME}.parquet", metadata={"season": "2025-26"})
    return tmp_path


@pytest.fixture
def g7_doc(g7_fact, g7_game, pbp_dir):
    return build_recap(
        _spec(pbp_dir),
        fact=g7_fact,
        posts=_posts(),
        games=_games(),
        player_games=_player_games(),
        pbp=g7_game,
        stamps=STAMPS,
    )


class TestSelectComments:
    """Every aligned comment, bodies by rule."""

    @pytest.fixture
    def comments(self, g7_fact, g7_periods) -> pl.DataFrame:
        aligned = align_comments(
            g7_fact.filter(pl.col("link_id") != PGT).with_columns(
                pl.lit(GAME).alias("game_id")
            ),
            g7_periods,
        )
        return select_comments(aligned, CHET_NAME)

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

    def test_the_rooms_two_loudest_per_bucket_keep_theirs(self, comments):
        """Scores 50 and 40 keep a body in the Q1 bucket; 30 does not."""
        by_id = {row["comment_id"]: row for row in comments.rows(named=True)}
        assert by_id["r50"]["body"] == "wemby!"
        assert by_id["r40"]["body"] == "refs"
        assert by_id["r30"]["body"] is None

    def test_ties_break_by_comment_id(self, g7_periods):
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
        )
        comments = select_comments(aligned, CHET_NAME)
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

    def test_post_id_is_the_thread(self, comments):
        """The split thread's comment names the split thread."""
        by_id = {row["comment_id"]: row["post_id"] for row in comments.rows(named=True)}
        assert by_id["f1"] == SPLIT
        assert by_id["b1"] == LIVE


class TestPeriodCountsAndSwing:
    """The Player x Game x Period rollup and the index hook."""

    @pytest.fixture
    def aligned(self, g7_fact, g7_periods) -> pl.DataFrame:
        return align_comments(
            g7_fact.filter(pl.col("link_id") != PGT).with_columns(
                pl.lit(GAME).alias("game_id")
            ),
            g7_periods,
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


class TestMeasureAnchors:
    """The alignment measured against the room, never moved."""

    @pytest.fixture
    def anchors(self, g7_doc) -> pl.DataFrame:
        return g7_doc.frames["anchors"]

    def test_conforms_and_lists_every_candidate(self, anchors):
        """The block and the steal are candidates, accepted or not."""
        validate_schema(anchors, RECAP_ANCHORS_SCHEMA, "anchors")
        validate_nullability(anchors, RECAP_NULLABLE_COLUMNS["anchors"], "anchors")
        assert anchors["action_id"].to_list() == [158, 210]
        assert anchors["keyword"].to_list() == ["block", "steal"]

    def test_pile_on_is_accepted_with_its_offset(self, anchors, g7_plays):
        """Three comments naming the block in one minute: accepted, and the
        offset is the first of them minus the play's mapped wall clock."""
        block = anchors.row(0, named=True)
        wall = _by_action(g7_plays, 158)["wall_clock"]
        assert block["accepted"] is True
        assert block["reaction_n"] == 3
        assert block["offset_seconds"] == block["first_reaction_utc"] - wall
        assert 0 < block["offset_seconds"] < 120

    def test_two_reactions_are_not_an_anchor(self, anchors):
        """The steal drew two: measured, not accepted, no offset."""
        steal = anchors.row(1, named=True)
        assert steal["accepted"] is False
        assert steal["reaction_n"] == 2
        assert steal["offset_seconds"] is None

    def test_no_reaction_leaves_nulls(self, g7_plays, g7_periods):
        """A candidate nobody named has no minute and no offset."""
        anchors = measure_anchors(g7_plays, pl.DataFrame(schema=RECAP_COMMENTS_SCHEMA))
        assert anchors["reaction_n"].to_list() == [0, 0]
        assert anchors["reaction_minute"].null_count() == 2
        assert error_seconds(anchors) is None

    def test_reaction_outside_the_window_is_ignored(self, g7_plays, g7_periods):
        """Naming the block nine minutes later is not a reaction to it."""
        wall = _by_action(g7_plays, 158)["wall_clock"]
        late = (wall // 60 + 9) * 60
        comments = select_comments(
            align_comments(
                _fact(
                    [_fact_row(f"l{i}", late + i, body="block") for i in range(3)]
                ).with_columns(pl.lit(GAME).alias("game_id")),
                g7_periods,
            ),
            CHET_NAME,
        )
        anchors = measure_anchors(g7_plays, comments)
        assert anchors.filter(pl.col("kind") == "block")["accepted"][0] is False

    def test_dunk_is_a_candidate_by_sub_type(self, g7_periods):
        """A made shot whose sub_type says Dunk is looked for as 'dunk'."""
        dunk = _chet(
            action_id=9,
            action_number=15,
            clock="PT10M00.00S",
            action_type="Made Shot",
            sub_type="Driving Dunk Shot",
            shot_result="Made",
            shot_value=2,
            score_home="4",
            score_away="4",
            description="Holmgren 1' Driving Dunk (4 PTS)",
        )
        plays = slice_plays(_pbp([*G7_MARKERS, dunk]), g7_periods, CHET_FOCUS)
        anchors = measure_anchors(plays, pl.DataFrame(schema=RECAP_COMMENTS_SCHEMA))
        assert anchors["keyword"].to_list() == ["dunk"]

    def test_error_is_the_largest_accepted_offset(self):
        """Signed offsets, absolute maximum, accepted rows only."""
        anchors = pl.DataFrame(
            {
                "action_id": [1, 2, 3],
                "kind": ["block"] * 3,
                "keyword": ["block"] * 3,
                "game_seconds": [1, 2, 3],
                "wall_clock": [10, 20, 30],
                "reaction_minute": [0, 0, 0],
                "reaction_n": [3, 3, 1],
                "first_reaction_utc": [40, 0, 0],
                "offset_seconds": [30, -45, None],
                "accepted": [True, True, False],
            },
            schema=RECAP_ANCHORS_SCHEMA,
        )
        assert error_seconds(anchors) == 45

    def test_the_timeline_is_not_moved(self, g7_doc, g7_plays):
        """The plays' wall clocks are the period-marker line, before and after."""
        assert (
            g7_doc.frames["plays"]["wall_clock"].to_list()
            == g7_plays["wall_clock"].to_list()
        )


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

    def test_frames_in_registry_order_and_valid(self, g7_doc):
        assert list(g7_doc.frames) == list(RECAP_FRAME_SCHEMAS)
        for name, schema in RECAP_FRAME_SCHEMAS.items():
            validate_schema(g7_doc.frames[name], schema, name)
            validate_nullability(
                g7_doc.frames[name], RECAP_NULLABLE_COLUMNS[name], name
            )

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
        assert 0 < entry["error_seconds"] < 120
        assert entry["population"] == "live_thread"
        assert (
            entry["game_id"],
            entry["attributed_player"],
            entry["player_id"],
            entry["slug"],
        ) == (GAME, CHET_NAME, CHET, "chet-holmgren")

    def test_minutes_reconcile_against_the_box_score(self, g7_doc):
        """32 stint minutes against a 33-minute line is a difference of -1."""
        assert stint_minutes(g7_doc.frames["stints"]) == 32
        assert g7_doc.entry["minutes_diff"] == -1

    def test_missing_box_score_line_raises(self, g7_fact, g7_game, pbp_dir):
        with pytest.raises(RecapError, match="no box-score line"):
            build_recap(
                _spec(pbp_dir),
                fact=g7_fact,
                posts=_posts(),
                games=_games(),
                player_games=_player_games().clear(),
                pbp=g7_game,
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
        assert any("scan skips" in r.message for r in caplog.records)


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
