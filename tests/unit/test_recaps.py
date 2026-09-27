"""
Tests for pipeline/recaps.py: the shared clock and what sits on it.

Frames are built locally: an action row in PLAY_BY_PLAY_SCHEMA's shape,
period markers with the archive's "(8:17 PM EST)" description, and a
comment row with the columns the alignment needs. Wall-clock expectations
are derived with zoneinfo in the test, never from the code under test.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from pipeline.recaps import (
    PERIOD_COLUMNS,
    RecapError,
    align_comments,
    build_periods,
    parse_clock_seconds,
    place_plays,
)
from pipeline.schemas import PLAY_BY_PLAY_SCHEMA

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
