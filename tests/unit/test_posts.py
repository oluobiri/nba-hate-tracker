"""Tests for pipeline/posts.py — the Post bridge from r/NBA posts to games."""

import logging
from datetime import date

import polars as pl
import pytest

from pipeline.posts import (
    GAME_THREAD,
    OTHER,
    POST_GAME_THREAD,
    build_game_index,
    build_title_name_map,
    classify_post,
    extract_team_pair,
    local_date,
    match_game,
    parse_score,
    parse_title_date,
)
from pipeline.schemas import GAMES_SCHEMA

TEAM_CONFIG = {
    "Boston Celtics": {"abbreviation": "BOS", "aliases": ["bos", "celtics"]},
    "New York Knicks": {"abbreviation": "NYK", "aliases": ["nyk", "knicks"]},
    "Los Angeles Clippers": {
        "abbreviation": "LAC",
        "aliases": ["lac", "clippers", "la clippers"],
    },
    "Orlando Magic": {
        "abbreviation": "ORL",
        "aliases": ["orl", "magic", "orland magic"],
    },
    "Portland Trail Blazers": {
        "abbreviation": "POR",
        "aliases": ["por", "trail blazers", "portland trailblazers"],
    },
    "Washington Wizards": {"abbreviation": "WAS", "aliases": ["was", "wizards"]},
    "Toronto Raptors": {"abbreviation": "TOR", "aliases": ["tor", "raptors"]},
}
NAME_MAP = build_title_name_map(TEAM_CONFIG)

# 2026-01-21 02:31 UTC = 2026-01-20 21:31 ET; 2026-01-21 06:30 UTC = 01:30 ET
_EVENING_ET = 1768962682
_AFTER_MIDNIGHT_ET = 1768977000


def _game(game_id, home, away, game_date, home_score=100, away_score=90) -> dict:
    """One GAMES_SCHEMA row with the fields matching cares about."""
    return {
        "game_id": game_id,
        "game_date": game_date,
        "season_type": "regular_season",
        "nba_cup_final": False,
        "neutral_site": False,
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
        "winner": home if home_score > away_score else away,
        "playoff_round": None,
        "playoff_series": None,
        "playoff_game": None,
    }


def _games(rows) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=GAMES_SCHEMA)


class TestClassifyPost:
    """Tests for classify_post (flair first, anchored title fallback)."""

    @pytest.mark.parametrize(
        "flair,expected",
        [
            ("Game Thread", GAME_THREAD),
            ("Post Game Thread", POST_GAME_THREAD),
            ("Highlight", OTHER),
            ("Index Thread", OTHER),
        ],
    )
    def test_flair_decides(self, flair, expected):
        """Verify the two thread flairs classify on flair alone; any other
        flair is `other` whatever the title says."""
        title = "GAME THREAD: Boston Celtics (1-0) @ New York Knicks (0-1)"
        assert classify_post(title, flair) == expected

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("GAME THREAD: Boston Celtics (1-0) @ New York Knicks (0-1)", GAME_THREAD),
            ("[Game Thread] The Boston Celtics VS the New York Knicks", GAME_THREAD),
            ("Game Thread 2: Boston Celtics vs New York Knicks", GAME_THREAD),
            (
                "[Post Game Thread] The Celtics defeat the Knicks, 99-84.",
                POST_GAME_THREAD,
            ),
            (
                "Post-Game Thread: Boston Celtics defeat New York Knicks",
                POST_GAME_THREAD,
            ),
            ("Daily Discussion Thread + Game Thread Index", OTHER),
            ("Inside the NBA was great", OTHER),
        ],
    )
    def test_unflaired_title_fallback_is_anchored(self, title, expected):
        """Verify a flair-stripped post classifies by an anchored title
        prefix only — "game thread" mid-title never matches."""
        assert classify_post(title, None) == expected


class TestBuildTitleNameMap:
    """Tests for build_title_name_map (canonical names + multi-word aliases)."""

    def test_canonical_names_and_multiword_aliases_only(self):
        """Verify single-token aliases stay out: `was` and `tor` would
        match inside ordinary words of a post-game title."""
        assert NAME_MAP["boston celtics"] == "Boston Celtics"
        assert NAME_MAP["orland magic"] == "Orlando Magic"
        assert NAME_MAP["la clippers"] == "Los Angeles Clippers"
        for single in ("was", "tor", "bos", "celtics", "wizards"):
            assert single not in NAME_MAP


class TestExtractTeamPair:
    """Tests for extract_team_pair (unordered pair from a title)."""

    @pytest.mark.parametrize(
        "title",
        [
            "GAME THREAD: Boston Celtics (2-0) @ New York Knicks (0-2) - (October 04, 2025)",
            "GAME THREAD: Boston Celtics (2-0) @ New York Knicks (0-2) — (October 04, 2025)",
            "GAME THREAD:Boston Celtics (2-0) @ New York Knicks (0-2) - (October 04, 2025)",
            "Game Thread: New York Knicks (1-3) vs Boston Celtics (3-1) Live Score | NBA Playoffs | Apr 28, 2026",
            "Game Thread: Boston Celtics vs New York Knicks Live Score | NBA | Feb 9, 2026",
            "Game Thread 2: New York Knicks (3-1) vs Boston Celtics (1-3) Live Score | NBA Finals | Jun 13, 2026",
            "[Game Thread] The Boston Celtics (0-0) VS the New York Knicks (0-0)",
            "[Post Game Thread] The New York Knicks (1-0) defeat the Boston Celtics (0-1), 99-84.",
            "Post-Game Thread: Boston Celtics defeat New York Knicks, 123-91 | NBA Playoffs | Apr 19, 2026",
        ],
    )
    def test_every_title_format_yields_the_pair(self, title):
        """Verify the three game-thread formats, the em dash, the missing
        space, the numbered thread and both post-game forms all parse."""
        assert extract_team_pair(title, NAME_MAP) == frozenset(
            {"Boston Celtics", "New York Knicks"}
        )

    @pytest.mark.parametrize(
        "title,expected",
        [
            (
                "GAME THREAD: Boston Celtics (1-0) @ Orland Magic (1-1) - (October 25, 2025)",
                {"Boston Celtics", "Orlando Magic"},
            ),
            (
                "Game Thread: LA Clippers vs Boston Celtics Live Score | NBA | Feb 20, 2026",
                {"Boston Celtics", "Los Angeles Clippers"},
            ),
            (
                "GAME THREAD: Portland Trailblazers (1-0) @ Boston Celtics (1-1) - (October 26, 2025)",
                {"Boston Celtics", "Portland Trail Blazers"},
            ),
        ],
    )
    def test_title_aliases_normalize(self, title, expected):
        """Verify teams.yaml title spellings resolve to the canonical name."""
        assert extract_team_pair(title, NAME_MAP) == frozenset(expected)

    def test_single_token_aliases_never_fire(self):
        """Verify prose containing `was` and `victory` names no third team."""
        title = (
            "[Post Game Thread] The Boston Celtics (1-0) defeat the New York "
            "Knicks (0-1), 99-84. It was a victory for the ages."
        )
        assert extract_team_pair(title, NAME_MAP) == frozenset(
            {"Boston Celtics", "New York Knicks"}
        )

    @pytest.mark.parametrize(
        "title",
        [
            "Game thread: Inside the NBA (ESPN)",
            "GAME THREAD: 2026 NBA Draft (First Round)",
            "GAME THREAD: Hapoel Jerusalem B.C. (0-0) @ New York Knicks (0-0) - (October 05, 2025)",
            "[ Removed by moderator ]",
            "GAME THREAD: Boston Celtics (1-0) @ Boston Celtics (1-0)",
        ],
    )
    def test_fewer_than_two_distinct_teams_is_none(self, title):
        """Verify non-games, non-NBA opponents and a repeated name yield no pair."""
        assert extract_team_pair(title, NAME_MAP) is None


class TestParseTitleDate:
    """Tests for parse_title_date (the two dated title formats)."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("GAME THREAD: A (1-0) @ B (0-1) - (October 04, 2025)", date(2025, 10, 4)),
            (
                "Game Thread: A vs B Live Score | NBA Playoffs | Apr 28, 2026",
                date(2026, 4, 28),
            ),
            ("GAME THREAD: A (1-0) @ B (0-1) - (January 26, 2026", date(2026, 1, 26)),
            ("[Post Game Thread] The A (1-0) defeat the B (0-1), 99-84.", None),
            ("Game Thread: A (22-8) @ B (17-14) 12/27/2025", None),
        ],
    )
    def test_parses_month_day_year_only(self, title, expected):
        """Verify long and short month names parse; undated and slash
        dates return None (the created date covers them)."""
        assert parse_title_date(title) == expected


class TestParseScore:
    """Tests for parse_score (final score as an unordered pair)."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            (
                "[Post Game Thread] The A (14-10) defeat the B (10-14), 103-81.",
                {103, 81},
            ),
            (
                "[Post Game Thread] The A (14-10) defeat the B (10-14) 102-100",
                {102, 100},
            ),
            (
                "[Post Game Thread] The A (1-0) defeat the B (0-1), 135–134 in OT.",
                {135, 134},
            ),
            (
                "[Post Game Thread] The A (1-0) defeat the B (0-1), 101-94 with 28/8/7",
                {101, 94},
            ),
            ("[Post Game Thread] The A (14-10) defeat the B (10-14) in Game 3", None),
        ],
    )
    def test_records_are_never_mistaken_for_the_score(self, title, expected):
        """Verify (W-L) records are stripped before the score is read."""
        assert parse_score(title) == expected


class TestLocalDate:
    """Tests for local_date (the ET calendar day of a UTC timestamp)."""

    def test_evening_and_after_midnight_share_the_game_day(self):
        """Verify 21:31 ET and 01:30 ET the next morning read as the same
        day in UTC-shifted terms: the second is the previous ET day."""
        assert local_date(_EVENING_ET) == date(2026, 1, 20)
        assert local_date(_AFTER_MIDNIGHT_ET) == date(2026, 1, 21)


class TestMatchGame:
    """Tests for match_game (pair + created date window, tie-break ladder)."""

    PAIR = frozenset({"Boston Celtics", "New York Knicks"})

    def _index(self, rows):
        return build_game_index(_games(rows))

    def test_same_et_day(self):
        """Verify a thread created the evening of the game links to it."""
        index = self._index(
            [
                _game(
                    "0022500001", "Boston Celtics", "New York Knicks", date(2026, 1, 20)
                )
            ]
        )
        assert match_game(self.PAIR, _EVENING_ET, None, None, index) == "0022500001"

    def test_post_game_after_midnight_et_links_to_the_previous_day(self):
        """Verify the ET window reaches back one day for late tips."""
        index = self._index(
            [
                _game(
                    "0022500001", "Boston Celtics", "New York Knicks", date(2026, 1, 20)
                )
            ]
        )
        assert match_game(self.PAIR, _AFTER_MIDNIGHT_ET, None, None, index) == (
            "0022500001"
        )

    def test_title_date_a_day_off_does_not_block_the_link(self):
        """Verify a wrong title date (the mod's UTC rollover) is ignored
        when only one game sits in the window."""
        index = self._index(
            [
                _game(
                    "0022500001", "Boston Celtics", "New York Knicks", date(2026, 1, 20)
                )
            ]
        )
        assert (
            match_game(self.PAIR, _EVENING_ET, date(2026, 1, 21), None, index)
            == "0022500001"
        )

    def test_orientation_is_irrelevant(self):
        """Verify home/away order in the index never matters to the pair."""
        index = self._index(
            [
                _game(
                    "0022500001", "New York Knicks", "Boston Celtics", date(2026, 1, 20)
                )
            ]
        )
        assert match_game(self.PAIR, _EVENING_ET, None, None, index) == "0022500001"

    def test_back_to_back_breaks_on_title_date(self):
        """Verify two games in the window resolve by the title date first."""
        index = self._index(
            [
                _game(
                    "0022500001", "Boston Celtics", "New York Knicks", date(2026, 1, 20)
                ),
                _game(
                    "0022500002", "Boston Celtics", "New York Knicks", date(2026, 1, 21)
                ),
            ]
        )
        assert (
            match_game(self.PAIR, _EVENING_ET, date(2026, 1, 21), None, index)
            == "0022500002"
        )

    def test_back_to_back_breaks_on_score(self):
        """Verify without a title date the score set picks the game."""
        index = self._index(
            [
                _game(
                    "0022500001",
                    "Boston Celtics",
                    "New York Knicks",
                    date(2026, 1, 20),
                    100,
                    90,
                ),
                _game(
                    "0022500002",
                    "Boston Celtics",
                    "New York Knicks",
                    date(2026, 1, 21),
                    111,
                    108,
                ),
            ]
        )
        assert match_game(self.PAIR, _EVENING_ET, None, {108, 111}, index) == (
            "0022500002"
        )

    def test_back_to_back_falls_back_to_the_created_day(self):
        """Verify with neither title date nor score the ET day decides."""
        index = self._index(
            [
                _game(
                    "0022500001", "Boston Celtics", "New York Knicks", date(2026, 1, 20)
                ),
                _game(
                    "0022500002", "Boston Celtics", "New York Knicks", date(2026, 1, 21)
                ),
            ]
        )
        assert match_game(self.PAIR, _EVENING_ET, None, None, index) == "0022500001"

    def test_no_game_in_window_is_none(self):
        """Verify a pair with no game within a day of creation stays unlinked."""
        index = self._index(
            [
                _game(
                    "0022500001", "Boston Celtics", "New York Knicks", date(2026, 1, 10)
                )
            ]
        )
        assert match_game(self.PAIR, _EVENING_ET, None, None, index) is None

    def test_unresolvable_tie_is_none_and_warns(self, caplog):
        """Verify a tie the ladder cannot break yields null, logged."""
        index = self._index(
            [
                _game(
                    "0022500001",
                    "Boston Celtics",
                    "New York Knicks",
                    date(2026, 1, 21),
                    100,
                    90,
                ),
                _game(
                    "0022500002",
                    "New York Knicks",
                    "Boston Celtics",
                    date(2026, 1, 21),
                    100,
                    90,
                ),
            ]
        )
        with caplog.at_level(logging.WARNING, logger="pipeline.posts"):
            assert match_game(self.PAIR, _AFTER_MIDNIGHT_ET, None, None, index) is None
        assert "Ambiguous" in caplog.text
