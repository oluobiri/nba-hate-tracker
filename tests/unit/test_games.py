"""Tests for pipeline/games.py — the Game dimension and player box-score lines."""

import logging
from datetime import date

import polars as pl
import pytest

from pipeline.games import (
    PLAYER_GAME_LOG_FILENAME,
    TEAM_GAME_LOG_FILENAME,
    build_games,
    build_player_games,
    load_game_tables,
)
from pipeline.schemas import (
    GAMES_SCHEMA,
    PLAYER_GAME_LOG_SCHEMA,
    PLAYER_GAMES_SCHEMA,
    TEAM_GAME_LOG_SCHEMA,
)
from utils.season_config import get_active_season

TEAM_CONFIG = {
    "Boston Celtics": {"abbreviation": "BOS", "team_id": 2},
    "New York Knicks": {"abbreviation": "NYK", "team_id": 3},
    "Los Angeles Lakers": {"abbreviation": "LAL", "team_id": 1},
}
ABBR_TO_TEAM = {info["abbreviation"]: team for team, info in TEAM_CONFIG.items()}
TEAM_IDS = {"BOS": 2, "NYK": 3, "LAL": 1, "MEL": 99}

PLAYER_METADATA = {
    "LeBron James": {"player_id": 2544, "team": "Los Angeles Lakers"},
    "Jayson Tatum": {"player_id": 1628369, "team": "Boston Celtics"},
    "Ben Simmons": {"player_id": 1627732, "team": None},
}
ATTRIBUTED = {"LeBron James", "Jayson Tatum", "Ben Simmons"}

_BOX = {
    "minutes": 30,
    "fgm": 5,
    "fga": 10,
    "fg3m": 1,
    "fg3a": 3,
    "ftm": 2,
    "fta": 2,
    "oreb": 1,
    "dreb": 4,
    "reb": 5,
    "ast": 3,
    "stl": 1,
    "blk": 0,
    "tov": 2,
    "pf": 2,
    "pts": 13,
    "plus_minus": 4,
}


def _team_row(
    game_id: str,
    team: str,
    opp: str,
    home: bool,
    pts: int,
    wl: str,
    *,
    season_type: str = "Regular Season",
    game_date: date = date(2025, 11, 1),
) -> dict:
    """One TEAM_GAME_LOG_SCHEMA row; the matchup encodes home/away."""
    return {
        "season_type": season_type,
        "game_id": game_id,
        "game_date": game_date,
        "team_id": TEAM_IDS[team],
        "team_abbr": team,
        "team_name": team,
        "matchup": f"{team} {'vs.' if home else '@'} {opp}",
        "wl": wl,
        **{**_BOX, "pts": pts},
    }


def _game_rows(
    game_id: str,
    home: str,
    away: str,
    home_pts: int,
    away_pts: int,
    **kwargs,
) -> list[dict]:
    """Both rows of a normal (non-neutral) game."""
    home_won = home_pts > away_pts
    return [
        _team_row(
            game_id, home, away, True, home_pts, "W" if home_won else "L", **kwargs
        ),
        _team_row(
            game_id, away, home, False, away_pts, "L" if home_won else "W", **kwargs
        ),
    ]


def _team_log(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=TEAM_GAME_LOG_SCHEMA)


def _player_row(
    game_id: str,
    player_id: int,
    team: str,
    opp: str,
    home: bool,
    *,
    season_type: str = "Regular Season",
    **box,
) -> dict:
    """One PLAYER_GAME_LOG_SCHEMA row."""
    return {
        "season_type": season_type,
        "game_id": game_id,
        "game_date": date(2025, 11, 1),
        "player_id": player_id,
        "player_name": f"player {player_id}",
        "team_id": TEAM_IDS[team],
        "team_abbr": team,
        "matchup": f"{team} {'vs.' if home else '@'} {opp}",
        "wl": "W",
        **{**_BOX, **box},
    }


def _player_log(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=PLAYER_GAME_LOG_SCHEMA)


@pytest.fixture
def two_games() -> pl.DataFrame:
    """A Celtics home win over the Knicks and a Lakers home loss to Boston."""
    return _team_log(
        _game_rows("0022500010", "BOS", "NYK", 110, 100)
        + _game_rows("0022500011", "LAL", "BOS", 95, 99, game_date=date(2025, 11, 2))
    )


class TestBuildGames:
    """Tests for build_games (team log -> Game dimension)."""

    def test_pivots_two_lines_into_one_game(self, two_games):
        """Home/away, scores and winner come from the two team lines."""
        games = build_games(two_games, ABBR_TO_TEAM)

        assert games.schema == GAMES_SCHEMA
        row = games.row(by_predicate=pl.col("game_id") == "0022500010", named=True)
        assert row["home_team"] == "Boston Celtics"
        assert row["away_team"] == "New York Knicks"
        assert (row["home_score"], row["away_score"]) == (110, 100)
        assert row["winner"] == "Boston Celtics"
        assert row["neutral_site"] is False
        assert row["season_type"] == "regular_season"
        assert row["nba_cup_final"] is False

    def test_away_winner(self, two_games):
        """An away win names the away team as winner."""
        games = build_games(two_games, ABBR_TO_TEAM)

        row = games.row(by_predicate=pl.col("game_id") == "0022500011", named=True)
        assert row["winner"] == "Boston Celtics"
        assert row["home_team"] == "Los Angeles Lakers"

    def test_sorted_by_date_then_id(self, two_games):
        """Output order is chronological regardless of input order."""
        games = build_games(two_games.reverse(), ABBR_TO_TEAM)

        assert games["game_id"].to_list() == ["0022500010", "0022500011"]

    def test_neutral_site_assigns_sides_by_team_id(self):
        """Both lines read "@": the game is flagged and the higher team_id
        is home, whichever row the endpoint served first."""
        rows = [
            _team_row("0062500001", "NYK", "BOS", False, 124, "W"),
            _team_row("0062500001", "BOS", "NYK", False, 113, "L"),
        ]

        forward = build_games(_team_log(rows), ABBR_TO_TEAM)
        reverse = build_games(_team_log(rows[::-1]), ABBR_TO_TEAM)

        assert forward.equals(reverse)
        row = forward.row(0, named=True)
        assert row["neutral_site"] is True
        assert row["home_team"] == "New York Knicks"  # team_id 3 > 2
        assert row["away_team"] == "Boston Celtics"
        assert (row["home_score"], row["away_score"]) == (124, 113)
        assert row["winner"] == "New York Knicks"

    def test_cup_final_prefix_is_regular_season_with_the_flag(self):
        """Prefix 006 (the IST-only game) maps to regular_season, cup flag set."""
        rows = [
            _team_row("0062500001", "NYK", "BOS", False, 124, "W", season_type="IST"),
            _team_row("0062500001", "BOS", "NYK", False, 113, "L", season_type="IST"),
        ]

        row = build_games(_team_log(rows), ABBR_TO_TEAM).row(0, named=True)

        assert row["season_type"] == "regular_season"
        assert row["nba_cup_final"] is True

    @pytest.mark.parametrize(
        "game_id,expected",
        [
            ("0012500001", "pre_season"),
            ("0022500001", "regular_season"),
            ("0052500001", "play_in"),
            ("0042500101", "playoffs"),
        ],
    )
    def test_season_type_decodes_from_the_id_prefix(self, game_id: str, expected: str):
        """The id prefix, not the endpoint label, sets season_type."""
        rows = _game_rows(game_id, "BOS", "NYK", 100, 90, season_type="Regular Season")

        games = build_games(_team_log(rows), ABBR_TO_TEAM)

        assert games["season_type"][0] == expected

    def test_unknown_id_prefix_raises(self):
        """An id prefix outside the decoder is unknown data, not a default."""
        rows = _game_rows("0032500001", "BOS", "NYK", 100, 90)

        with pytest.raises(ValueError, match="no season type"):
            build_games(_team_log(rows), ABBR_TO_TEAM)

    def test_playoff_fields_parse_from_the_id(self):
        """004 YY 00 R S G: round, series and game come from the id."""
        rows = _game_rows("0042500317", "BOS", "NYK", 100, 90, season_type="Playoffs")

        row = build_games(_team_log(rows), ABBR_TO_TEAM).row(0, named=True)

        assert (row["playoff_round"], row["playoff_series"], row["playoff_game"]) == (
            3,
            1,
            7,
        )

    def test_playoff_fields_null_outside_the_playoffs(self, two_games):
        """A regular-season id carries null playoff fields."""
        games = build_games(two_games, ABBR_TO_TEAM)

        assert games["playoff_round"].null_count() == games.height

    def test_drops_preseason_games_against_non_nba_opponents(self, two_games, caplog):
        """An unknown abbreviation in the preseason drops the whole game,
        the NBA side's line included, with a logged count."""
        exhibition = [
            _team_row(
                "0012500009", "BOS", "MEL", True, 107, "W", season_type="Pre Season"
            ),
            _team_row(
                "0012500009", "MEL", "BOS", False, 90, "L", season_type="Pre Season"
            ),
        ]

        with caplog.at_level(logging.INFO, logger="pipeline.games"):
            games = build_games(
                pl.concat([two_games, _team_log(exhibition)]), ABBR_TO_TEAM
            )

        assert "0012500009" not in games["game_id"].to_list()
        assert games.height == 2
        assert "Dropped 1 preseason game(s)" in caplog.text
        assert "MEL" in caplog.text

    def test_unknown_abbreviation_outside_preseason_raises(self):
        """A non-preseason unknown abbreviation is a config gap, not an exhibition."""
        rows = [
            _team_row("0022500009", "BOS", "MEL", True, 107, "W"),
            _team_row("0022500009", "MEL", "BOS", False, 90, "L"),
        ]

        with pytest.raises(ValueError, match="unknown to teams.yaml"):
            build_games(_team_log(rows), ABBR_TO_TEAM)

    def test_single_line_game_raises(self, two_games):
        """A game with one team line breaks the grain and fails loudly."""
        lone = [_team_row("0022500099", "BOS", "NYK", True, 100, "W")]

        with pytest.raises(ValueError, match="two per game"):
            build_games(pl.concat([two_games, _team_log(lone)]), ABBR_TO_TEAM)

    def test_wl_disagreeing_with_scores_raises(self):
        """A W on the lower score is corrupt input, not a tie-break."""
        rows = [
            _team_row("0022500010", "BOS", "NYK", True, 90, "W"),
            _team_row("0022500010", "NYK", "BOS", False, 100, "L"),
        ]

        with pytest.raises(ValueError, match="disagrees with the scores"):
            build_games(_team_log(rows), ABBR_TO_TEAM)

    def test_missing_wl_raises(self):
        """A null W/L on a team line is an unfinished game, never a winner guess."""
        rows = [
            _team_row("0022500010", "BOS", "NYK", True, 100, None),
            _team_row("0022500010", "NYK", "BOS", False, 90, "L"),
        ]

        with pytest.raises(ValueError, match="missing or disagrees"):
            build_games(_team_log(rows), ABBR_TO_TEAM)

    def test_two_hosts_raises(self):
        """Both lines reading "vs." is malformed, not a neutral site."""
        rows = [
            _team_row("0022500010", "BOS", "NYK", True, 100, "W"),
            _team_row("0022500010", "NYK", "BOS", True, 90, "L"),
        ]

        with pytest.raises(ValueError, match="both teams as host"):
            build_games(_team_log(rows), ABBR_TO_TEAM)

    def test_null_matchup_raises(self):
        """A null matchup cannot place a side and fails loudly."""
        rows = _game_rows("0022500010", "BOS", "NYK", 100, 90)
        rows[1]["matchup"] = None

        with pytest.raises(ValueError, match="null matchup"):
            build_games(_team_log(rows), ABBR_TO_TEAM)


@pytest.fixture
def games(two_games) -> pl.DataFrame:
    return build_games(two_games, ABBR_TO_TEAM)


@pytest.fixture
def player_log() -> pl.DataFrame:
    """Tatum in both games, LeBron in the second, plus an untracked player."""
    return _player_log(
        [
            _player_row("0022500010", 1628369, "BOS", "NYK", True, pts=30),
            _player_row("0022500011", 1628369, "BOS", "LAL", False, pts=25),
            _player_row("0022500011", 2544, "LAL", "BOS", True, pts=28, plus_minus=-4),
            _player_row("0022500011", 999, "LAL", "BOS", True),
        ]
    )


class TestBuildPlayerGames:
    """Tests for build_player_games (player log -> attributed lines)."""

    def test_keeps_attributed_players_only(self, player_log, games):
        """Untracked players are dropped; tracked ones join by player_id."""
        lines = build_player_games(
            player_log, games, PLAYER_METADATA, ABBR_TO_TEAM, ATTRIBUTED
        )

        assert lines.schema == PLAYER_GAMES_SCHEMA
        assert lines.height == 3
        assert set(lines["attributed_player"]) == {"Jayson Tatum", "LeBron James"}

    def test_labels_team_opponent_and_home(self, player_log, games):
        """roster_team/opponent are canonical names; is_home follows games.home_team."""
        lines = build_player_games(
            player_log, games, PLAYER_METADATA, ABBR_TO_TEAM, ATTRIBUTED
        )

        tatum_away = lines.row(
            by_predicate=(pl.col("game_id") == "0022500011")
            & (pl.col("attributed_player") == "Jayson Tatum"),
            named=True,
        )
        assert tatum_away["roster_team"] == "Boston Celtics"
        assert tatum_away["opponent"] == "Los Angeles Lakers"
        assert tatum_away["is_home"] is False
        assert tatum_away["pts"] == 25
        lebron = lines.row(by_predicate=pl.col("player_id") == 2544, named=True)
        assert lebron["is_home"] is True
        assert lebron["plus_minus"] == -4

    def test_excludes_attributed_players_outside_the_dimension(self, player_log, games):
        """attributed_players narrows the set below the config's tracked ids."""
        lines = build_player_games(
            player_log, games, PLAYER_METADATA, ABBR_TO_TEAM, {"LeBron James"}
        )

        assert lines["attributed_player"].to_list() == ["LeBron James"]

    def test_drops_lines_of_games_not_in_the_dimension(self, player_log, games):
        """A line for a game absent from games (e.g. a dropped exhibition) goes too."""
        extra = _player_log(
            [
                _player_row(
                    "0012500009", 1628369, "BOS", "MEL", True, season_type="Pre Season"
                )
            ]
        )

        lines = build_player_games(
            pl.concat([player_log, extra]),
            games,
            PLAYER_METADATA,
            ABBR_TO_TEAM,
            ATTRIBUTED,
        )

        assert "0012500009" not in lines["game_id"].to_list()

    def test_players_without_lines_are_absent_and_logged(
        self, player_log, games, caplog
    ):
        """A tracked player with no line has no row - never a fabricated one."""
        with caplog.at_level(logging.INFO, logger="pipeline.games"):
            lines = build_player_games(
                player_log, games, PLAYER_METADATA, ABBR_TO_TEAM, ATTRIBUTED
            )

        assert "Ben Simmons" not in lines["attributed_player"].to_list()
        assert "no game lines: ['Ben Simmons']" in caplog.text

    def test_is_home_is_null_on_a_neutral_site(self, player_log):
        """Neither side hosted a neutral-site game; the line says so with null."""
        neutral = _team_log(
            [
                _team_row("0062500001", "NYK", "BOS", False, 124, "W"),
                _team_row("0062500001", "BOS", "NYK", False, 113, "L"),
            ]
        )
        games = build_games(neutral, ABBR_TO_TEAM)
        extra = _player_log([_player_row("0062500001", 1628369, "BOS", "NYK", False)])

        lines = build_player_games(
            extra, games, PLAYER_METADATA, ABBR_TO_TEAM, ATTRIBUTED
        )

        assert lines.schema == PLAYER_GAMES_SCHEMA
        assert lines["is_home"][0] is None

    def test_duplicate_line_raises(self, player_log, games):
        """A player twice in one game breaks the grain and fails loudly."""
        dup = _player_log([_player_row("0022500011", 2544, "LAL", "BOS", True)])

        with pytest.raises(ValueError, match="one row per game x player"):
            build_player_games(
                pl.concat([player_log, dup]),
                games,
                PLAYER_METADATA,
                ABBR_TO_TEAM,
                ATTRIBUTED,
            )


class TestLoadGameTables:
    """Tests for load_game_tables (snapshots on disk -> the two tables)."""

    def test_missing_snapshots_degrade_to_empty_tables(self, tmp_path, caplog):
        """No snapshot: warn and return empty, schema-conforming frames."""
        with caplog.at_level(logging.WARNING, logger="pipeline.games"):
            games, player_games, meta = load_game_tables(
                tmp_path, PLAYER_METADATA, TEAM_CONFIG, ATTRIBUTED
            )

        assert games.schema == GAMES_SCHEMA and games.height == 0
        assert player_games.schema == PLAYER_GAMES_SCHEMA and player_games.height == 0
        assert meta == {
            "game_count": 0,
            "player_game_count": 0,
            "games_fetched_at": None,
        }
        assert "run scripts.fetch_games" in caplog.text

    def test_builds_from_snapshots_and_reads_the_stamp(
        self, tmp_path, two_games, player_log
    ):
        """Both tables build from disk; fetched_at comes from the team log's stamp."""
        two_games.write_parquet(
            tmp_path / TEAM_GAME_LOG_FILENAME,
            metadata={"season": "2025-26", "fetched_at": "2026-09-12"},
        )
        player_log.write_parquet(tmp_path / PLAYER_GAME_LOG_FILENAME)

        games, player_games, meta = load_game_tables(
            tmp_path, PLAYER_METADATA, TEAM_CONFIG, ATTRIBUTED
        )

        assert games.height == 2
        assert player_games.height == 3
        assert meta["games_fetched_at"] == "2026-09-12"

    def test_season_stamp_mismatch_warns_for_either_snapshot(
        self, tmp_path, two_games, player_log, caplog
    ):
        """Each snapshot's season stamp is checked; a stale player log warns too."""
        two_games.write_parquet(
            tmp_path / TEAM_GAME_LOG_FILENAME, metadata={"season": get_active_season()}
        )
        player_log.write_parquet(
            tmp_path / PLAYER_GAME_LOG_FILENAME, metadata={"season": "1999-00"}
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.games"):
            load_game_tables(tmp_path, PLAYER_METADATA, TEAM_CONFIG, ATTRIBUTED)

        assert "player_game_log.parquet: season stamp '1999-00' does not match" in (
            caplog.text
        )

    def test_differing_fetch_dates_warn(self, tmp_path, two_games, player_log, caplog):
        """The two logs are one fetch; different fetch dates mean a torn snapshot."""
        two_games.write_parquet(
            tmp_path / TEAM_GAME_LOG_FILENAME, metadata={"fetched_at": "2026-09-12"}
        )
        player_log.write_parquet(
            tmp_path / PLAYER_GAME_LOG_FILENAME, metadata={"fetched_at": "2026-09-01"}
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.games"):
            _, _, meta = load_game_tables(
                tmp_path, PLAYER_METADATA, TEAM_CONFIG, ATTRIBUTED
            )

        assert "different fetch dates" in caplog.text
        assert meta["games_fetched_at"] == "2026-09-12"
