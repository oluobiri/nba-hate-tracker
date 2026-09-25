"""Tests for pipeline/nba_stats.py stats.nba.com acquisition."""

import json
import logging
from datetime import date
from unittest.mock import Mock, call, patch

import pandas as pd
import polars as pl
import pytest
import requests

from pipeline.nba_stats import (
    fetch_play_by_play,
    fetch_player_game_log,
    fetch_rosters,
    fetch_team_game_log,
    has_valid_play_by_play,
    sync_play_by_play,
)
from pipeline.schemas import (
    PLAY_BY_PLAY_SCHEMA,
    PLAYER_GAME_LOG_SCHEMA,
    ROSTERS_SCHEMA,
    SCHEMA_VERSION,
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


# ---------------------------------------------------------------------------
# Play-by-play (PlayByPlayV3)
# ---------------------------------------------------------------------------

GAME_A = "0042500317"
GAME_B = "0042500405"


def _raw_action(**overrides) -> dict:
    """One endpoint-shaped PlayByPlayV3 action (camelCase nba_api columns)."""
    row = {
        "gameId": GAME_A,
        "actionNumber": 4,
        "clock": "PT12M00.00S",
        "period": 1,
        "teamId": 1610612760,
        "teamTricode": "OKC",
        "personId": 1631096,
        "playerName": "Holmgren",
        "playerNameI": "C. Holmgren",
        "xLegacy": 0,
        "yLegacy": 0,
        "shotDistance": 0,
        "shotResult": "",
        "isFieldGoal": 0,
        "scoreHome": "",
        "scoreAway": "",
        "pointsTotal": 0,
        "location": "h",
        "description": "Jump Ball Holmgren vs. Wembanyama: Tip to Castle",
        "actionType": "Jump Ball",
        "subType": "",
        "videoAvailable": 1,
        "shotValue": 0,
        "actionId": 2,
    }
    row.update(overrides)
    return row


def _game_frame(game_id: str) -> pd.DataFrame:
    """A two-action raw frame: the period start, then a made shot with coordinates."""
    return pd.DataFrame(
        [
            _raw_action(
                gameId=game_id,
                actionNumber=2,
                teamId=0,
                teamTricode="",
                personId=0,
                playerName="",
                playerNameI="",
                scoreHome="0",
                scoreAway="0",
                location="",
                description="Start of 1st Period (8:17 PM EST)",
                actionType="period",
                subType="start",
                actionId=1,
            ),
            _raw_action(
                gameId=game_id,
                actionNumber=7,
                clock="PT11M39.00S",
                teamId=1610612759,
                teamTricode="SAS",
                personId=1641705,
                playerName="Wembanyama",
                playerNameI="V. Wembanyama",
                xLegacy=112,
                yLegacy=36,
                shotDistance=12,
                shotResult="Made",
                isFieldGoal=1,
                scoreHome="0",
                scoreAway="2",
                pointsTotal=2,
                location="v",
                description="Wembanyama 12' Step Back Bank Jump Shot (2 PTS)",
                actionType="Made Shot",
                subType="Step Back Bank Jump Shot",
                shotValue=2,
                actionId=3,
            ),
        ]
    )


def _pbp_endpoint(responses: dict[str, list]):
    """Build a PlayByPlayV3 stand-in serving queued responses per game id.

    Each queued item is a raw frame (served as the endpoint's first data
    frame) or an exception (raised by the call).
    """
    queues = {game_id: list(items) for game_id, items in responses.items()}

    def _make(game_id: str, timeout: int) -> Mock:
        item = queues[game_id].pop(0)
        if isinstance(item, Exception):
            raise item
        endpoint = Mock()
        endpoint.get_data_frames.return_value = [
            item,
            pd.DataFrame({"videoAvailable": [1]}),
        ]
        return endpoint

    return _make


def _sync_with_mocks(responses: dict[str, list], out_dir, game_ids=None, **kwargs):
    """Run sync_play_by_play with the endpoint and sleep mocked."""
    with (
        patch(
            "pipeline.nba_stats.playbyplayv3.PlayByPlayV3",
            side_effect=_pbp_endpoint(responses),
        ) as mock_endpoint,
        patch("pipeline.nba_stats.time.sleep") as mock_sleep,
    ):
        report = sync_play_by_play(
            game_ids if game_ids is not None else list(responses),
            out_dir,
            season="2025-26",
            **kwargs,
        )
    return report, mock_endpoint, mock_sleep


class TestFetchPlayByPlay:
    """Tests for PlayByPlayV3 normalization into the snapshot contract."""

    def _fetch(self, frame: pd.DataFrame) -> pl.DataFrame:
        with patch(
            "pipeline.nba_stats.playbyplayv3.PlayByPlayV3",
            side_effect=_pbp_endpoint({GAME_A: [frame]}),
        ):
            return fetch_play_by_play(GAME_A)

    def test_conforms_to_schema(self):
        """Every endpoint column lands, snake_cased, in schema order and dtype."""
        df = self._fetch(_game_frame(GAME_A))
        assert df.schema == PLAY_BY_PLAY_SCHEMA

    def test_snake_cases_the_trailing_initial(self):
        """playerNameI becomes player_name_i, not a mangled split."""
        df = self._fetch(_game_frame(GAME_A))
        assert df["player_name_i"].to_list() == ["", "V. Wembanyama"]

    def test_keeps_values_as_served(self):
        """Scores stay strings, the clock stays ISO, and empty strings stay empty."""
        df = self._fetch(_game_frame(GAME_A))
        shot = df.row(1, named=True)
        assert shot["score_away"] == "2"
        assert shot["clock"] == "PT11M39.00S"
        assert (shot["x_legacy"], shot["y_legacy"]) == (112, 36)
        assert df.row(0, named=True)["team_tricode"] == ""
        assert df.null_count().sum_horizontal().item() == 0

    def test_numeric_looking_strings_stay_strings(self):
        """A score served as a JSON number still lands as a string column."""
        frame = _game_frame(GAME_A)
        frame["scoreHome"] = [0, 0]  # serialization drift to raw numbers
        df = self._fetch(frame)
        assert df["score_home"].to_list() == ["0", "0"]

    def test_zero_actions_returns_empty_frame(self):
        """An unknown game serves zero rows; the fetch returns them, conformed."""
        df = self._fetch(_game_frame(GAME_A).iloc[0:0])
        assert df.height == 0
        assert df.schema == PLAY_BY_PLAY_SCHEMA


class TestSyncPlayByPlay:
    """Tests for the resumable, miss-collecting per-game archive."""

    def test_writes_one_stamped_file_per_game(self, tmp_path):
        """Each game lands at <game_id>.parquet with the lineage stamps."""
        report, _, _ = _sync_with_mocks(
            {GAME_A: [_game_frame(GAME_A)], GAME_B: [_game_frame(GAME_B)]}, tmp_path
        )

        assert report.ok
        assert report.fetched == [GAME_A, GAME_B]
        for game_id in (GAME_A, GAME_B):
            path = tmp_path / f"{game_id}.parquet"
            assert pl.read_parquet(path)["game_id"].unique().to_list() == [game_id]
            stamps = pl.read_parquet_metadata(path)
            assert stamps["season"] == "2025-26"
            assert stamps["schema_version"] == str(SCHEMA_VERSION)
            date.fromisoformat(stamps["fetched_at"])
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            f"{GAME_A}.parquet",
            f"{GAME_B}.parquet",
        ]  # no temp file left behind

    def test_skips_valid_file_on_disk(self, tmp_path):
        """A game with a valid file is not requested again."""
        _sync_with_mocks({GAME_A: [_game_frame(GAME_A)]}, tmp_path)

        report, mock_endpoint, mock_sleep = _sync_with_mocks({GAME_A: []}, tmp_path)

        assert mock_endpoint.call_count == 0
        assert mock_sleep.call_count == 0
        assert report.skipped == [GAME_A]
        assert report.fetched == []

    @pytest.mark.parametrize(
        "bad_bytes",
        [b"not a parquet", b""],
        ids=["corrupt", "empty"],
    )
    def test_refetches_invalid_file_on_disk(self, tmp_path, bad_bytes):
        """A file that does not read as a valid snapshot is fetched again."""
        (tmp_path / f"{GAME_A}.parquet").write_bytes(bad_bytes)

        report, mock_endpoint, _ = _sync_with_mocks(
            {GAME_A: [_game_frame(GAME_A)]}, tmp_path
        )

        assert mock_endpoint.call_count == 1
        assert report.fetched == [GAME_A]
        assert has_valid_play_by_play(tmp_path / f"{GAME_A}.parquet")

    def test_zero_actions_is_a_miss(self, tmp_path):
        """A game that serves no actions misses and leaves no file."""
        report, _, _ = _sync_with_mocks(
            {GAME_A: [_game_frame(GAME_A).iloc[0:0]]}, tmp_path
        )

        assert not report.ok
        assert [m.game_id for m in report.misses] == [GAME_A]
        assert "zero actions" in report.misses[0].reason
        assert not (tmp_path / f"{GAME_A}.parquet").exists()

    def test_transient_error_is_retried(self, tmp_path):
        """A timeout then a success writes the file; the retry is not a miss."""
        report, mock_endpoint, _ = _sync_with_mocks(
            {GAME_A: [requests.Timeout("hang"), _game_frame(GAME_A)]}, tmp_path
        )

        assert mock_endpoint.call_count == 2
        assert report.ok
        assert report.fetched == [GAME_A]

    def test_exhausted_retries_are_a_miss(self, tmp_path):
        """A game whose retries run out misses; the run continues."""
        down = [requests.ConnectionError("down")] * 2
        report, _, _ = _sync_with_mocks(
            {GAME_A: down, GAME_B: [_game_frame(GAME_B)]}, tmp_path, max_attempts=2
        )

        assert [m.game_id for m in report.misses] == [GAME_A]
        assert "ConnectionError" in report.misses[0].reason
        assert report.fetched == [GAME_B]

    @pytest.mark.parametrize(
        "error",
        [
            requests.HTTPError("500 Server Error"),
            json.JSONDecodeError("Expecting value", "", 0),
            KeyError("resultSets"),
        ],
        ids=["http", "json", "payload"],
    )
    def test_endpoint_failure_is_a_miss_not_a_crash(self, tmp_path, error):
        """A non-transient per-game failure misses once and the run moves on."""
        report, mock_endpoint, _ = _sync_with_mocks(
            {GAME_A: [error], GAME_B: [_game_frame(GAME_B)]}, tmp_path
        )

        assert mock_endpoint.call_count == 2  # no retries for GAME_A
        assert [m.game_id for m in report.misses] == [GAME_A]
        assert report.fetched == [GAME_B]
        assert not (tmp_path / f"{GAME_A}.parquet").exists()

    def test_endpoint_drift_is_a_miss(self, tmp_path):
        """A column the schema does not pin fails validation as a miss, no file."""
        drifted = _game_frame(GAME_A).assign(newColumn=1)
        report, _, _ = _sync_with_mocks(
            {GAME_A: [drifted], GAME_B: [_game_frame(GAME_B)]}, tmp_path
        )

        assert [m.game_id for m in report.misses] == [GAME_A]
        assert "new_column" in report.misses[0].reason
        assert report.fetched == [GAME_B]
        assert not (tmp_path / f"{GAME_A}.parquet").exists()

    def test_waits_after_every_request(self, tmp_path):
        """The polite delay follows every request, misses included."""
        report, _, mock_sleep = _sync_with_mocks(
            {
                GAME_A: [_game_frame(GAME_A).iloc[0:0]],
                GAME_B: [_game_frame(GAME_B)],
            },
            tmp_path,
            delay=0.6,
        )

        assert mock_sleep.call_args_list == [call(0.6), call(0.6)]
        assert len(report.misses) == 1


class TestHasValidPlayByPlay:
    """Tests for the on-disk validity check that makes the archive resumable."""

    def test_missing_file_is_invalid(self, tmp_path):
        """No file, nothing to skip."""
        assert not has_valid_play_by_play(tmp_path / f"{GAME_A}.parquet")

    def test_wrong_schema_is_invalid(self, tmp_path):
        """A parquet that does not match the contract is refetched."""
        path = tmp_path / f"{GAME_A}.parquet"
        pl.DataFrame({"game_id": [GAME_A]}).write_parquet(path)
        assert not has_valid_play_by_play(path)

    def test_zero_rows_is_invalid(self, tmp_path):
        """A conforming but empty parquet never counts as banked."""
        path = tmp_path / f"{GAME_A}.parquet"
        pl.DataFrame(schema=PLAY_BY_PLAY_SCHEMA).write_parquet(path)
        assert not has_valid_play_by_play(path)
