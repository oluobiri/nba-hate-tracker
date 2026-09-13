"""Tests for pipeline/nba_stats.py roster snapshot acquisition."""

import logging
from datetime import date
from unittest.mock import Mock, call, patch

import pandas as pd
import polars as pl
import pytest
import requests

from pipeline.nba_stats import (
    fetch_player_game_log,
    fetch_rosters,
    fetch_team_game_log,
)
from pipeline.schemas import (
    PLAYER_GAME_LOG_SCHEMA,
    ROSTERS_SCHEMA,
    TEAM_GAME_LOG_SCHEMA,
)

FAKE_TEAMS = [
    {"id": 1, "full_name": "Atlanta Hawks", "abbreviation": "ATL"},
    {"id": 2, "full_name": "Boston Celtics", "abbreviation": "BOS"},
]


def _raw_row(**overrides) -> dict:
    """One endpoint-shaped raw roster row (uppercase nba_api columns)."""
    row = {
        "TeamID": 1,
        "SEASON": "2025-26",
        "LeagueID": "00",
        "PLAYER": "Player One",
        "PLAYER_SLUG": "player-one",
        "NUM": "23",
        "POSITION": "F",
        "HEIGHT": "6-8",
        "WEIGHT": "230",
        "BIRTH_DATE": "MAR 03, 1998",
        "AGE": 27.0,
        "EXP": "5",
        "SCHOOL": "Duke",
        "PLAYER_ID": 100,
    }
    row.update(overrides)
    return row


def _endpoint_returning(frames_by_team: dict[int, pd.DataFrame]):
    """Build a CommonTeamRoster stand-in serving one raw frame per team_id."""

    def _make(team_id: int, season: str, timeout: int) -> Mock:
        endpoint = Mock()
        endpoint.get_data_frames.return_value = [frames_by_team[team_id]]
        return endpoint

    return _make


def _fetch_with_mocks(
    endpoint_side_effect, teams=FAKE_TEAMS, **fetch_kwargs
) -> tuple[pl.DataFrame, Mock, Mock]:
    """Run fetch_rosters with the endpoint, static teams, and sleep mocked."""
    with (
        patch("pipeline.nba_stats.static_teams.get_teams", return_value=teams),
        patch(
            "pipeline.nba_stats.commonteamroster.CommonTeamRoster",
            side_effect=endpoint_side_effect,
        ) as mock_endpoint,
        patch("pipeline.nba_stats.time.sleep") as mock_sleep,
    ):
        df = fetch_rosters("2025-26", **fetch_kwargs)
    return df, mock_endpoint, mock_sleep


def _two_team_frames() -> dict[int, pd.DataFrame]:
    """Raw frames for the two fake teams: a vet + a rookie, then one player.

    Team 1 mixes a veteran and a rookie so fixtures carry the endpoint's
    real shape heterogeneity (EXP "5" vs "R", NUM "23" vs "00", a null
    SCHOOL) instead of homogeneous single-row frames.
    """
    return {
        1: pd.DataFrame(
            [
                _raw_row(),
                _raw_row(
                    PLAYER="Rookie One",
                    PLAYER_ID=101,
                    NUM="00",
                    HEIGHT="7-1",
                    WEIGHT="232",
                    BIRTH_DATE="JUN 26, 2005",
                    AGE=21.0,
                    EXP="R",
                    SCHOOL=None,
                ),
            ]
        ),
        2: pd.DataFrame(
            [_raw_row(TeamID=2, PLAYER="Player Two", PLAYER_ID=200, NUM="0")]
        ),
    }


class TestFetchRosters:
    """Tests for endpoint normalization into the snapshot contract."""

    def test_conforms_to_rosters_schema(self):
        """The returned frame matches ROSTERS_SCHEMA exactly (names, dtypes, order)."""
        df, _, _ = _fetch_with_mocks(_endpoint_returning(_two_team_frames()))

        assert df.schema == ROSTERS_SCHEMA

    def test_keeps_height_and_weight(self):
        """HEIGHT/WEIGHT survive normalization (the notebook capture dropped them)."""
        df, _, _ = _fetch_with_mocks(_endpoint_returning(_two_team_frames()))

        by_player = {r["player_name"]: r for r in df.to_dicts()}
        assert by_player["Player One"]["height"] == "6-8"
        assert by_player["Player One"]["weight"] == "230"
        assert by_player["Rookie One"]["height"] == "7-1"
        assert by_player["Rookie One"]["weight"] == "232"

    def test_parses_birth_date(self):
        """The endpoint's 'MAR 03, 1998' string lands as a real Date."""
        df, _, _ = _fetch_with_mocks(_endpoint_returning(_two_team_frames()))

        by_player = {r["player_name"]: r for r in df.to_dicts()}
        assert by_player["Player One"]["birth_date"] == date(1998, 3, 3)
        assert by_player["Rookie One"]["birth_date"] == date(2005, 6, 26)

    def test_warns_on_unparseable_birth_date(self, caplog):
        """A birth date that doesn't match the format nulls with a warning."""
        frames = _two_team_frames()
        frames[2] = pd.DataFrame(
            [
                _raw_row(
                    TeamID=2,
                    PLAYER="Player Two",
                    PLAYER_ID=200,
                    BIRTH_DATE="1998-03-03",
                )
            ]
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.nba_stats"):
            df, _, _ = _fetch_with_mocks(_endpoint_returning(frames))

        by_player = {r["player_name"]: r for r in df.to_dicts()}
        assert by_player["Player Two"]["birth_date"] is None
        assert "1 birth_date value(s)" in caplog.text

    def test_no_warning_when_all_birth_dates_parse(self, caplog):
        """Endpoint-supplied nulls don't trigger the parse-failure warning."""
        with caplog.at_level(logging.WARNING, logger="pipeline.nba_stats"):
            _fetch_with_mocks(_endpoint_returning(_two_team_frames()))

        assert "birth_date" not in caplog.text

    def test_null_school_survives_as_null(self):
        """A missing SCHOOL value lands as null, not the string 'None'."""
        df, _, _ = _fetch_with_mocks(_endpoint_returning(_two_team_frames()))

        by_player = {r["player_name"]: r for r in df.to_dicts()}
        assert by_player["Rookie One"]["school"] is None

    def test_adds_team_literals_from_static_data(self):
        """team_name/team_abbr come from the static team list, one pair per team."""
        df, _, _ = _fetch_with_mocks(_endpoint_returning(_two_team_frames()))

        by_player = {r["player_name"]: r for r in df.to_dicts()}
        assert by_player["Player One"]["team_name"] == "Atlanta Hawks"
        assert by_player["Rookie One"]["team_abbr"] == "ATL"
        assert by_player["Player Two"]["team_name"] == "Boston Celtics"
        assert by_player["Player Two"]["team_abbr"] == "BOS"

    def test_coerces_numeric_serialized_string_columns(self):
        """Raw JSON ints in string-typed columns coerce instead of crashing.

        The endpoint serves EXP/NUM as strings today; if that serialization
        ever drifts to raw numbers, the mixed str/int object column must
        still convert (pl.from_pandas would otherwise raise ArrowInvalid).
        """
        frames = {
            1: pd.DataFrame([_raw_row(EXP=5, NUM=0), _raw_row(PLAYER_ID=101)]),
            2: pd.DataFrame(
                [_raw_row(TeamID=2, PLAYER="Player Two", PLAYER_ID=200, NUM="00")]
            ),
        }

        df, _, _ = _fetch_with_mocks(_endpoint_returning(frames))

        assert df.schema == ROSTERS_SCHEMA
        assert sorted(df["experience"].to_list()) == ["5", "5", "5"]
        assert sorted(df["jersey_number"].to_list()) == ["0", "00", "23"]

    def test_passes_season_and_timeout_to_endpoint(self):
        """Every endpoint call carries the requested season and timeout."""
        _, mock_endpoint, _ = _fetch_with_mocks(
            _endpoint_returning(_two_team_frames()), timeout=45
        )

        assert mock_endpoint.call_count == len(FAKE_TEAMS)
        for call_args in mock_endpoint.call_args_list:
            assert call_args.kwargs["season"] == "2025-26"
            assert call_args.kwargs["timeout"] == 45

    def test_sleeps_between_teams(self):
        """The politeness delay runs once per team request."""
        _, _, mock_sleep = _fetch_with_mocks(
            _endpoint_returning(_two_team_frames()), delay=0.6
        )

        assert mock_sleep.call_args_list == [call(0.6), call(0.6)]


class TestRetry:
    """Tests for the bounded retry loop around endpoint calls."""

    def test_transient_timeout_then_success(self):
        """A timeout is retried and the fetch still completes."""
        frames = _two_team_frames()
        make = _endpoint_returning(frames)
        attempts = iter([requests.Timeout("hang"), make(1, "2025-26", 30)])

        def _flaky(team_id: int, season: str, timeout: int) -> Mock:
            if team_id == 1:
                result = next(attempts)
                if isinstance(result, Exception):
                    raise result
                return result
            return make(team_id, season, timeout)

        df, mock_endpoint, _ = _fetch_with_mocks(_flaky)

        assert mock_endpoint.call_count == 3  # team 1 twice, team 2 once
        assert df.height == 3

    def test_exhaustion_raises_with_backoff_schedule(self):
        """Persistent timeouts raise after max_attempts, backing off exponentially."""

        def _always_timeout(team_id: int, season: str, timeout: int) -> Mock:
            raise requests.Timeout("hang")

        with pytest.raises(requests.Timeout):
            _fetch_with_mocks(_always_timeout, max_attempts=4, retry_backoff=2.0)

        # Re-run capturing sleep to assert the schedule (no delay sleeps: the
        # first team never succeeds, so only backoff sleeps happen).
        with (
            patch("pipeline.nba_stats.static_teams.get_teams", return_value=FAKE_TEAMS),
            patch(
                "pipeline.nba_stats.commonteamroster.CommonTeamRoster",
                side_effect=_always_timeout,
            ),
            patch("pipeline.nba_stats.time.sleep") as mock_sleep,
        ):
            with pytest.raises(requests.Timeout):
                fetch_rosters("2025-26", max_attempts=4, retry_backoff=2.0)

        assert mock_sleep.call_args_list == [call(2.0), call(4.0), call(8.0)]

    def test_non_retryable_error_raises_immediately(self):
        """A non-transient error propagates without retries."""

        def _http_error(team_id: int, season: str, timeout: int) -> Mock:
            raise requests.HTTPError("400 Client Error")

        with (
            patch("pipeline.nba_stats.static_teams.get_teams", return_value=FAKE_TEAMS),
            patch(
                "pipeline.nba_stats.commonteamroster.CommonTeamRoster",
                side_effect=_http_error,
            ) as mock_endpoint,
            patch("pipeline.nba_stats.time.sleep"),
        ):
            with pytest.raises(requests.HTTPError):
                fetch_rosters("2025-26")

        assert mock_endpoint.call_count == 1

    def test_failed_team_kills_the_whole_fetch(self):
        """A team that exhausts retries fails the fetch — no partial snapshot."""
        frames = _two_team_frames()
        make = _endpoint_returning(frames)

        def _second_team_down(team_id: int, season: str, timeout: int) -> Mock:
            if team_id == 2:
                raise requests.ConnectionError("down")
            return make(team_id, season, timeout)

        with pytest.raises(requests.ConnectionError):
            _fetch_with_mocks(_second_team_down, max_attempts=2)


# ---------------------------------------------------------------------------
# Game logs (LeagueGameLog)
# ---------------------------------------------------------------------------

_RAW_BOX = {
    "MIN": 240,
    "FGM": 40,
    "FGA": 88,
    "FG_PCT": 0.455,
    "FG3M": 12,
    "FG3A": 35,
    "FG3_PCT": 0.343,
    "FTM": 18,
    "FTA": 22,
    "FT_PCT": 0.818,
    "OREB": 10,
    "DREB": 34,
    "REB": 44,
    "AST": 25,
    "STL": 7,
    "BLK": 5,
    "TOV": 13,
    "PF": 19,
    "PTS": 110,
    "PLUS_MINUS": 10,
    "VIDEO_AVAILABLE": 1,
}


def _raw_team_line(**overrides) -> dict:
    """One endpoint-shaped team line (uppercase LeagueGameLog columns)."""
    row = {
        "SEASON_ID": "22025",
        "TEAM_ID": 1610612738,
        "TEAM_ABBREVIATION": "BOS",
        "TEAM_NAME": "Boston Celtics",
        "GAME_ID": "0022500001",
        "GAME_DATE": "2025-10-21",
        "MATCHUP": "BOS vs. NYK",
        "WL": "W",
        **_RAW_BOX,
    }
    row.update(overrides)
    return row


def _raw_player_line(**overrides) -> dict:
    """One endpoint-shaped player line."""
    row = {
        "SEASON_ID": "22025",
        "PLAYER_ID": 1628369,
        "PLAYER_NAME": "Jayson Tatum",
        "TEAM_ID": 1610612738,
        "TEAM_ABBREVIATION": "BOS",
        "TEAM_NAME": "Boston Celtics",
        "GAME_ID": "0022500001",
        "GAME_DATE": "2025-10-21",
        "MATCHUP": "BOS vs. NYK",
        "WL": "W",
        **{**_RAW_BOX, "MIN": 36, "PTS": 30, "PLUS_MINUS": 12},
        "FANTASY_PTS": 55.5,
    }
    row.update(overrides)
    return row


def _game_log_endpoint(pages: dict[str, list[dict]]):
    """Build a LeagueGameLog stand-in serving one raw frame per season type.

    A season type absent from `pages` serves an empty frame with the
    endpoint's column set, as stats.nba.com does before a phase starts.
    """
    columns = list(_raw_player_line().keys())

    def _make(**kwargs) -> Mock:
        rows = pages.get(kwargs["season_type_all_star"], [])
        endpoint = Mock()
        endpoint.get_data_frames.return_value = [
            pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns)
        ]
        return endpoint

    return _make


def _fetch_log_with_mocks(
    endpoint_side_effect, fetch, **fetch_kwargs
) -> tuple[pl.DataFrame, Mock, Mock]:
    """Run a game-log fetch with the endpoint and sleep mocked."""
    with (
        patch(
            "pipeline.nba_stats.leaguegamelog.LeagueGameLog",
            side_effect=endpoint_side_effect,
        ) as mock_endpoint,
        patch("pipeline.nba_stats.time.sleep") as mock_sleep,
    ):
        df = fetch("2025-26", **fetch_kwargs)
    return df, mock_endpoint, mock_sleep


def _one_game_pages() -> dict[str, list[dict]]:
    """A regular-season game (both lines) re-listed under IST, plus the Cup final."""
    game = [
        _raw_team_line(),
        _raw_team_line(
            TEAM_ID=1610612752,
            TEAM_ABBREVIATION="NYK",
            TEAM_NAME="New York Knicks",
            MATCHUP="NYK @ BOS",
            WL="L",
            PTS=100,
            PLUS_MINUS=-10,
        ),
    ]
    cup_final = [
        _raw_team_line(
            GAME_ID="0062500001", GAME_DATE="2025-12-16", MATCHUP="BOS @ NYK"
        ),
        _raw_team_line(
            GAME_ID="0062500001",
            GAME_DATE="2025-12-16",
            TEAM_ID=1610612752,
            TEAM_ABBREVIATION="NYK",
            TEAM_NAME="New York Knicks",
            MATCHUP="NYK @ BOS",
            WL="L",
            PTS=100,
        ),
    ]
    return {"Regular Season": game, "IST": game + cup_final}


class TestFetchTeamGameLog:
    """Tests for fetch_team_game_log (LeagueGameLog team lines)."""

    def test_conforms_to_schema(self):
        """The union of every season type lands as TEAM_GAME_LOG_SCHEMA."""
        df, _, _ = _fetch_log_with_mocks(
            _game_log_endpoint(_one_game_pages()), fetch_team_game_log
        )

        assert df.schema == TEAM_GAME_LOG_SCHEMA
        assert df["game_date"][0] == date(2025, 10, 21)

    def test_drops_ist_relistings_and_keeps_the_cup_final(self):
        """Group games already in the regular-season page are dropped from
        IST; the Cup final, present only there, survives under its label."""
        df, _, _ = _fetch_log_with_mocks(
            _game_log_endpoint(_one_game_pages()), fetch_team_game_log
        )

        assert df.height == 4
        by_game = df.group_by("game_id").agg(pl.col("season_type").unique())
        assert by_game.row(by_predicate=pl.col("game_id") == "0022500001")[1] == [
            "Regular Season"
        ]
        assert by_game.row(by_predicate=pl.col("game_id") == "0062500001")[1] == ["IST"]

    def test_fetches_every_season_type_with_season_and_timeout(self):
        """One page per season type, all carrying season, kind and timeout."""
        _, mock_endpoint, mock_sleep = _fetch_log_with_mocks(
            _game_log_endpoint(_one_game_pages()), fetch_team_game_log, timeout=45
        )

        requested = [
            c.kwargs["season_type_all_star"] for c in mock_endpoint.call_args_list
        ]
        assert requested == [
            "Pre Season",
            "Regular Season",
            "IST",
            "PlayIn",
            "Playoffs",
        ]
        for call_args in mock_endpoint.call_args_list:
            assert call_args.kwargs["season"] == "2025-26"
            assert call_args.kwargs["player_or_team_abbreviation"] == "T"
            assert call_args.kwargs["timeout"] == 45
        assert mock_sleep.call_count == 5

    def test_duplicate_outside_ist_raises(self):
        """The same team line twice under one season type is an endpoint fault."""
        pages = {"Regular Season": [_raw_team_line(), _raw_team_line()]}

        with pytest.raises(ValueError, match="one row per game_id x team_id"):
            _fetch_log_with_mocks(_game_log_endpoint(pages), fetch_team_game_log)

    def test_transient_timeout_is_retried(self):
        """A page that times out once still lands on the retry."""
        make = _game_log_endpoint(_one_game_pages())
        attempts = iter([requests.Timeout("hang")])

        def _flaky(**kwargs) -> Mock:
            if kwargs["season_type_all_star"] == "Regular Season":
                error = next(attempts, None)
                if error:
                    raise error
            return make(**kwargs)

        df, mock_endpoint, _ = _fetch_log_with_mocks(_flaky, fetch_team_game_log)

        assert mock_endpoint.call_count == 6
        assert df.height == 4


class TestFetchPlayerGameLog:
    """Tests for fetch_player_game_log (LeagueGameLog player lines)."""

    def test_conforms_to_schema_and_keeps_every_player(self):
        """All players land, tracked or not; the tracked cut is aggregation's."""
        pages = {
            "Regular Season": [
                _raw_player_line(),
                _raw_player_line(PLAYER_ID=999, PLAYER_NAME="Two-Way Guy", MIN=2),
            ]
        }

        df, mock_endpoint, _ = _fetch_log_with_mocks(
            _game_log_endpoint(pages), fetch_player_game_log
        )

        assert df.schema == PLAYER_GAME_LOG_SCHEMA
        assert df["player_id"].to_list() == [999, 1628369]
        assert mock_endpoint.call_args.kwargs["player_or_team_abbreviation"] == "P"

    def test_null_wl_survives_as_null(self):
        """A line with no W/L (it happens) keeps a null, not the string "None"."""
        pages = {"Regular Season": [_raw_player_line(WL=None)]}

        df, _, _ = _fetch_log_with_mocks(
            _game_log_endpoint(pages), fetch_player_game_log
        )

        assert df["wl"][0] is None
