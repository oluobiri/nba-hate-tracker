"""Tests for pipeline/posts.py — the Post bridge from r/NBA posts to games."""

import json
import logging
from datetime import date

import polars as pl
import pytest

from pipeline.posts import (
    DISCUSSION,
    GAME_THREAD,
    HIGHLIGHT,
    INJURY,
    LOWLIGHT,
    NEWS,
    OTHER,
    POST_GAME_THREAD,
    POSTS_BRIDGE_FILENAME,
    RAW_POSTS_SCHEMA,
    build_game_index,
    build_posts_bridge,
    build_title_name_map,
    classify_post,
    extract_team_pair,
    leading_tag,
    load_posts_table,
    local_date,
    match_game,
    parse_score,
    parse_title_date,
    post_source,
    read_raw_posts,
)
from pipeline.schemas import GAMES_SCHEMA, POSTS_SCHEMA
from utils.season_config import get_active_season
from utils.team_config import load_team_config_version

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


class TestLeadingTag:
    """Tests for leading_tag (the bracketed tag a title opens with)."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("[Charania] The Bucks have traded ...", "charania"),
            ("  [ The  Athletic ] Inside the deal", "the athletic"),
            ("[O’Connor] Ja Morant isn't ...", "o'connor"),
            ("[STAT REPORT] SGA has more ...", "stat report"),
        ],
    )
    def test_normalizes_case_spacing_and_apostrophes(self, title, expected):
        """Verify one source spelled two ways yields one tag."""
        assert leading_tag(title) == expected

    @pytest.mark.parametrize(
        "title",
        [
            "[[Scotto] Kawhi Leonard has been named ...",
            "[[Scotto]] Kawhi Leonard has been named ...",
        ],
    )
    def test_doubled_bracket_reads_the_tag_inside(self, title):
        """Verify a mistyped double bracket never enters the tag."""
        assert leading_tag(title) == "scotto"

    def test_forty_characters_is_the_longest_tag(self):
        """Verify the length bound: a tag of forty reads, forty-one does not."""
        assert leading_tag(f"[{'a' * 40}] title") == "a" * 40
        assert leading_tag(f"[{'a' * 41}] title") is None

    @pytest.mark.parametrize(
        "title",
        [
            "Charania says the Bucks have traded ...",
            "The Bucks [per Charania] have traded ...",
            "[] empty brackets",
            "[" + "a very long bracketed sentence " * 3 + "] then a title",
        ],
    )
    def test_no_tag_is_none(self, title):
        """Verify only a short tag at the head of the title counts."""
        assert leading_tag(title) is None


class TestClassifyPost:
    """Tests for classify_post (flair first, anchored title fallback)."""

    @pytest.mark.parametrize(
        "flair,expected",
        [
            ("Game Thread", GAME_THREAD),
            ("Post Game Thread", POST_GAME_THREAD),
            ("Highlight", HIGHLIGHT),
            ("Discussion", DISCUSSION),
            ("Original Content", DISCUSSION),
            ("AMA", DISCUSSION),
            ("All-Access", DISCUSSION),
            ("Index Thread", OTHER),
            ("Misleading", OTHER),
        ],
    )
    def test_flair_decides(self, flair, expected):
        """Verify a flair classifies on flair alone, whatever the title
        says, and an unmapped flair is `other`."""
        title = "[Charania] GAME THREAD: Boston Celtics @ New York Knicks"
        assert classify_post(title, flair) == expected

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("[Highlight] Jaylen Brown dunks on two defenders", HIGHLIGHT),
            ("[Highlights] Every Wembanyama block tonight", HIGHLIGHT),
            ("[Lowlight] Airball to end the half", LOWLIGHT),
            ("[Lowlights] Every turnover of the fourth", LOWLIGHT),
            ("[Injury] Player X is helped off the floor", INJURY),
            ("[Injury Update] Player X is questionable to return", INJURY),
            ("[Higlight] A misspelled dunk", HIGHLIGHT),
        ],
    )
    def test_unflaired_convention_tag_names_the_type(self, title, expected):
        """Verify the tags that are types in themselves classify a post
        the mods left unflaired."""
        assert classify_post(title, None) == expected

    @pytest.mark.parametrize(
        "title",
        [
            "[Charania] The Bucks have traded ...",
            "[The Athletic] Inside the deal",
            "[Stein/Fischer] The Wolves, sources say, ...",
            "[Jaylen Brown] Analytics are ruining the game",
            "[247Sports] A recruit commits",
            "[Стейн] A source written outside the Latin alphabet",
        ],
    )
    def test_unflaired_source_tag_is_news(self, title):
        """Verify any other leading tag is a source: a reporter, an
        outlet, or the person quoted."""
        assert classify_post(title, None) == NEWS

    @pytest.mark.parametrize(
        "title",
        [
            "[OC] Playoff risers and fallers by game score",
            "[Serious] Do the Spurs have to move off of Fox?",
            "[ Removed by moderator ]",
            "[Highlight Request] The airball from last night",
            "[[Highlight Request] The airball from last night",
            "[Post Game] Wembanyama tonight: 26 points, 15 rebounds",
            "[02/04/2025] Dennis Schröder on the trade deadline",
            "[2022] Jrue Holiday forces two turnovers",
            "[2026 NBA Draft] #12 Pick: selected by Oklahoma City",
            "The Bucks [per Charania] have traded ...",
        ],
    )
    def test_conventions_and_dates_stay_other(self, title):
        """Verify a tag that names no source is not news: the
        subreddit's conventions, a date, a tag opening with a year."""
        assert classify_post(title, None) == OTHER

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


class TestPostSource:
    """Tests for post_source (the tag of a news post, null elsewhere)."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("[Charania] The Bucks have traded ...", "charania"),
            ("[Marc Stein] League sources say ...", "marc stein"),
            ("[Jaylen Brown] Analytics are ruining the game", "jaylen brown"),
        ],
    )
    def test_news_post_carries_its_tag(self, title, expected):
        """Verify the source is the normalized leading tag."""
        assert post_source(title, None) == expected

    @pytest.mark.parametrize(
        "title,flair",
        [
            ("[Charania] The Bucks have traded ...", "Highlight"),
            ("[Charania] The Bucks have traded ...", "Misleading"),
            ("[Lowlight] Airball to end the half", None),
            ("[ Removed by moderator ]", None),
            ("[Game Thread] The Celtics VS the Knicks", None),
            ("Inside the NBA was great", None),
        ],
    )
    def test_every_other_type_has_no_source(self, title, flair):
        """Verify a source is never read off a post that is not news."""
        assert post_source(title, flair) is None


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

    def test_first_two_teams_in_title_order(self):
        """Verify a third team named later in the title never displaces
        the matchup, whatever the spellings' lengths."""
        title = (
            "[Post Game Thread] The Orlando Magic (3-2) defeat the Boston "
            "Celtics to advance and face the Los Angeles Clippers (2-3), 110-98."
        )
        assert extract_team_pair(title, NAME_MAP) == frozenset(
            {"Orlando Magic", "Boston Celtics"}
        )

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


def _post(post_id, title, created_utc, flair, num_comments=10, score=5) -> dict:
    """One raw-projected post row (the read_raw_posts shape)."""
    return {
        "post_id": post_id,
        "title": title,
        "created_utc": created_utc,
        "score": score,
        "num_comments": num_comments,
        "link_flair_text": flair,
    }


def _posts(rows) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=RAW_POSTS_SCHEMA)


class TestReadRawPosts:
    """Tests for read_raw_posts (streamed projection of the download)."""

    def test_projects_the_bridge_fields(self, tmp_path):
        """Verify only the six source fields survive, keyed by the t3_
        fullname, with a null flair kept null."""
        path = tmp_path / "r_nba_posts.jsonl"
        path.write_text(
            json.dumps(
                {
                    "id": "abc",
                    "name": "t3_abc",
                    "title": "GAME THREAD: A @ B",
                    "created_utc": 1768962682,
                    "score": 12,
                    "num_comments": 340,
                    "link_flair_text": "Game Thread",
                    "selftext": "long body",
                    "author": "NBA_MOD",
                }
            )
            + "\n"
            + json.dumps(
                {
                    "id": "def",
                    "name": "t3_def",
                    "title": "Some highlight",
                    "created_utc": 1768962700,
                    "score": 1,
                    "num_comments": 0,
                    "link_flair_text": None,
                }
            )
            + "\n"
        )

        posts = read_raw_posts(path)

        assert posts.schema == RAW_POSTS_SCHEMA
        assert posts["post_id"].to_list() == ["t3_abc", "t3_def"]
        assert posts["link_flair_text"].to_list() == ["Game Thread", None]
        assert posts["num_comments"].to_list() == [340, 0]


class TestBuildPostsBridge:
    """Tests for build_posts_bridge (every post -> type, game, primary flag)."""

    GAMES = [
        _game(
            "0022500001", "Boston Celtics", "New York Knicks", date(2026, 1, 20), 99, 84
        ),
    ]
    ROWS = [
        _post(
            "t3_gt1",
            "GAME THREAD: New York Knicks (0-1) @ Boston Celtics (1-0) - (January 21, 2026)",
            _EVENING_ET,
            "Game Thread",
            num_comments=30,
        ),
        _post(
            "t3_gt2",
            "Game Thread: Boston Celtics vs New York Knicks Live Score | NBA | Jan 20, 2026 (Second Half)",
            _EVENING_ET + 3600,
            "Game Thread",
            num_comments=100,
        ),
        _post(
            "t3_pgt",
            "[Post Game Thread] The Boston Celtics (1-0) defeat the New York Knicks (0-1), 99-84.",
            _AFTER_MIDNIGHT_ET,
            None,
            num_comments=500,
        ),
        _post(
            "t3_tnt", "Game thread: Inside the NBA (ESPN)", _EVENING_ET, "Game Thread"
        ),
        _post(
            "t3_hl", "Jaylen Brown dunks", _EVENING_ET, "Highlight", num_comments=900
        ),
    ]

    def test_bridge_shape_and_links(self, caplog):
        """Verify split threads share the game, the largest is primary,
        the flair-stripped post-game thread links through the ET window,
        the non-game keeps a null game_id and other posts stay other."""
        with caplog.at_level(logging.INFO, logger="pipeline.posts"):
            bridge = build_posts_bridge(
                _posts(self.ROWS), _games(self.GAMES), TEAM_CONFIG
            )

        assert bridge.schema == POSTS_SCHEMA
        by_id = {row["post_id"]: row for row in bridge.iter_rows(named=True)}
        assert by_id["t3_gt1"]["game_id"] == "0022500001"
        assert by_id["t3_gt2"]["game_id"] == "0022500001"
        assert by_id["t3_gt1"]["is_primary"] is False
        assert by_id["t3_gt2"]["is_primary"] is True
        assert by_id["t3_pgt"]["post_type"] == POST_GAME_THREAD
        assert by_id["t3_pgt"]["game_id"] == "0022500001"
        assert by_id["t3_pgt"]["is_primary"] is True
        assert by_id["t3_tnt"]["post_type"] == GAME_THREAD
        assert by_id["t3_tnt"]["game_id"] is None
        assert by_id["t3_tnt"]["is_primary"] is False
        assert by_id["t3_hl"]["post_type"] == HIGHLIGHT
        assert by_id["t3_hl"]["game_id"] is None
        assert bridge["source"].null_count() == bridge.height
        assert "game_thread: 2/3 linked" in caplog.text
        assert "post_game_thread: 1/1 linked" in caplog.text
        assert "1/1 games" in caplog.text
        assert "Inside the NBA" in caplog.text

    def test_only_threads_are_resolved_to_a_game(self, caplog):
        """Verify a typed post that names both teams of a game played
        that day keeps a null game_id, a news post carries its source,
        and the build logs the types and the sources it found."""
        rows = [
            _post(
                "t3_hl",
                "[Highlight] Boston Celtics beat the New York Knicks at the buzzer",
                _EVENING_ET,
                None,
            ),
            _post(
                "t3_news",
                "[Charania] The Boston Celtics and New York Knicks agree to a trade",
                _EVENING_ET,
                None,
            ),
        ]

        with caplog.at_level(logging.INFO, logger="pipeline.posts"):
            bridge = build_posts_bridge(_posts(rows), _games(self.GAMES), TEAM_CONFIG)

        by_id = {row["post_id"]: row for row in bridge.iter_rows(named=True)}
        assert by_id["t3_hl"]["post_type"] == HIGHLIGHT
        assert by_id["t3_hl"]["source"] is None
        assert by_id["t3_news"]["post_type"] == NEWS
        assert by_id["t3_news"]["source"] == "charania"
        assert bridge["game_id"].null_count() == 2
        assert not bridge["is_primary"].any()
        assert "highlight 1, lowlight 0, injury 0, news 1, discussion 0" in caplog.text
        assert "news sources: 1 distinct; largest: charania 1\n" in caplog.text

    def test_no_news_logs_no_sources(self, caplog):
        """Verify a bridge without a news post reports none, and names none."""
        with caplog.at_level(logging.INFO, logger="pipeline.posts"):
            build_posts_bridge(_posts(self.ROWS), _games(self.GAMES), TEAM_CONFIG)

        assert "news sources: 0 distinct\n" in caplog.text

    def test_sorted_by_creation_then_id(self):
        """Verify the bridge is ordered like the fact, by time then key."""
        bridge = build_posts_bridge(_posts(self.ROWS), _games(self.GAMES), TEAM_CONFIG)

        assert bridge["post_id"].to_list() == [
            "t3_gt1",
            "t3_hl",
            "t3_tnt",
            "t3_gt2",
            "t3_pgt",
        ]

    def test_duplicate_post_id_raises(self):
        """Verify the one-row-per-post grain is enforced at the build."""
        rows = [self.ROWS[0], {**self.ROWS[0], "title": "repost"}]

        with pytest.raises(ValueError, match="one row per post"):
            build_posts_bridge(_posts(rows), _games(self.GAMES), TEAM_CONFIG)

    def test_null_num_comments_never_wins_primary(self):
        """Verify a thread with no comment count ranks last, not first."""
        rows = [self.ROWS[0], {**self.ROWS[1], "num_comments": None}]

        bridge = build_posts_bridge(_posts(rows), _games(self.GAMES), TEAM_CONFIG)

        by_id = {row["post_id"]: row for row in bridge.iter_rows(named=True)}
        assert by_id["t3_gt1"]["is_primary"] is True
        assert by_id["t3_gt2"]["is_primary"] is False

    def test_no_games_leaves_every_thread_unlinked(self):
        """Verify an empty Game dimension still classifies, links nothing."""
        bridge = build_posts_bridge(_posts(self.ROWS), _games([]), TEAM_CONFIG)

        assert bridge["game_id"].null_count() == bridge.height
        assert not bridge["is_primary"].any()
        assert bridge.filter(pl.col("post_type") == GAME_THREAD).height == 3


class TestLoadPostsTable:
    """Tests for load_posts_table (bridge -> published subset at aggregation)."""

    GAMES = [
        _game("0022500001", "Boston Celtics", "New York Knicks", date(2026, 1, 20)),
    ]
    BRIDGE = [
        {
            **_post("t3_gt", "GAME THREAD: ...", _EVENING_ET, "Game Thread"),
            "post_type": GAME_THREAD,
            "source": None,
            "game_id": "0022500001",
            "is_primary": True,
        },
        {
            **_post("t3_receipt", "Trade rumor", _EVENING_ET, None),
            "post_type": OTHER,
            "source": None,
            "game_id": None,
            "is_primary": False,
        },
        {
            **_post("t3_noise", "Highlight", _EVENING_ET, "Highlight"),
            "post_type": HIGHLIGHT,
            "source": None,
            "game_id": None,
            "is_primary": False,
        },
        {
            **_post("t3_news", "[Charania] A trade", _EVENING_ET, None),
            "post_type": NEWS,
            "source": "charania",
            "game_id": None,
            "is_primary": False,
        },
    ]
    RECEIPTS = pl.DataFrame({"link_id": ["t3_receipt", "t3_receipt", "t3_missing"]})

    def _write_bridge(
        self,
        ref_dir,
        rows=None,
        *,
        season=None,
        games_fetched_at="2026-09-12",
        teams_config_version=None,
    ):
        stamps = {
            "season": season or get_active_season(),
            "processed_at": "2026-09-13",
            "games_fetched_at": games_fetched_at,
            "teams_config_version": teams_config_version or load_team_config_version(),
        }
        pl.DataFrame(rows or self.BRIDGE, schema=POSTS_SCHEMA).write_parquet(
            ref_dir / POSTS_BRIDGE_FILENAME, metadata=stamps
        )

    def test_missing_bridge_degrades_to_empty(self, tmp_path, caplog):
        """Verify aggregation stays runnable before the bridge exists."""
        with caplog.at_level(logging.WARNING, logger="pipeline.posts"):
            posts, metadata = load_posts_table(
                tmp_path, _games(self.GAMES), "2026-09-12", self.RECEIPTS
            )

        assert posts.schema == POSTS_SCHEMA
        assert posts.height == 0
        assert metadata == {"post_count": 0, "posts_processed_at": None}
        assert "scripts.process_posts" in caplog.text

    def test_publishes_threads_and_receipt_posts(self, tmp_path):
        """Verify the subset is every thread plus each post a receipt
        points at, and nothing else: a typed post that is neither stays
        in the bridge."""
        self._write_bridge(tmp_path)

        posts, metadata = load_posts_table(
            tmp_path, _games(self.GAMES), "2026-09-12", self.RECEIPTS
        )

        assert posts["post_id"].to_list() == ["t3_gt", "t3_receipt"]
        assert metadata == {"post_count": 2, "posts_processed_at": "2026-09-13"}

    def test_game_id_absent_from_games_fails_the_build(self, tmp_path):
        """Verify a bridge pointing at a game the dimension lacks raises."""
        self._write_bridge(tmp_path)

        with pytest.raises(ValueError, match="absent from games"):
            load_posts_table(tmp_path, _games([]), "2026-09-12", self.RECEIPTS)

    def test_bridge_of_another_shape_names_the_remedy(self, tmp_path):
        """Verify a bridge written before a column was added fails the
        build with the command that rebuilds it."""
        stale = pl.DataFrame(self.BRIDGE, schema=POSTS_SCHEMA).drop("source")
        stale.write_parquet(
            tmp_path / POSTS_BRIDGE_FILENAME,
            metadata={
                "season": get_active_season(),
                "processed_at": "2026-09-13",
                "games_fetched_at": "2026-09-12",
                "teams_config_version": load_team_config_version(),
            },
        )

        with pytest.raises(ValueError, match="missing columns.*process_posts --force"):
            load_posts_table(tmp_path, _games(self.GAMES), "2026-09-12", self.RECEIPTS)

    def test_fetch_date_mismatch_warns(self, tmp_path, caplog):
        """Verify a bridge derived from another game-log fetch is flagged."""
        self._write_bridge(tmp_path, games_fetched_at="2026-09-01")

        with caplog.at_level(logging.WARNING, logger="pipeline.posts"):
            load_posts_table(tmp_path, _games(self.GAMES), "2026-09-12", self.RECEIPTS)

        assert "2026-09-01" in caplog.text and "2026-09-12" in caplog.text

    def test_teams_config_drift_warns(self, tmp_path, caplog):
        """Verify a bridge derived under another teams.yaml is flagged: a
        later alias fix would leave it silently under-matching titles."""
        self._write_bridge(tmp_path, teams_config_version="0.1")

        with caplog.at_level(logging.WARNING, logger="pipeline.posts"):
            load_posts_table(tmp_path, _games(self.GAMES), "2026-09-12", self.RECEIPTS)

        assert "teams_config_version drift" in caplog.text
        assert "'0.1'" in caplog.text

    def test_season_stamp_mismatch_warns(self, tmp_path, caplog):
        """Verify a bridge built for another season is read, not silently."""
        self._write_bridge(tmp_path, season="1999-00")

        with caplog.at_level(logging.WARNING, logger="pipeline.posts"):
            load_posts_table(tmp_path, _games(self.GAMES), "2026-09-12", self.RECEIPTS)

        assert "1999-00" in caplog.text
