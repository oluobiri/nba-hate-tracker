"""Tests for pipeline/nba_stats.py roster snapshot acquisition."""

import logging
from datetime import date
from unittest.mock import Mock, call, patch

import pandas as pd
import polars as pl
import pytest
import requests

from pipeline.nba_stats import fetch_rosters
from pipeline.schemas import ROSTERS_SCHEMA

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
