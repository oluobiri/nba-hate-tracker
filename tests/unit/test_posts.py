"""Tests for pipeline/posts.py — the Post bridge from r/NBA posts to games."""

import json
import logging
from datetime import date

import polars as pl
import pytest

from pipeline.posts import (
    GAME_THREAD,
    OTHER,
    POST_GAME_THREAD,
    POSTS_BRIDGE_FILENAME,
    RAW_POSTS_SCHEMA,
    build_game_index,
    build_posts_bridge,
    build_title_name_map,
    classify_post,
    extract_team_pair,
    load_posts_table,
    local_date,
    match_game,
    parse_score,
    parse_title_date,
    read_raw_posts,
)
from pipeline.schemas import GAMES_SCHEMA, POSTS_SCHEMA
from utils.season_config import get_active_season

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
        assert by_id["t3_hl"]["post_type"] == OTHER
        assert by_id["t3_hl"]["game_id"] is None
        assert "game_thread: 2/3 linked" in caplog.text
        assert "post_game_thread: 1/1 linked" in caplog.text
        assert "1/1 games" in caplog.text
        assert "Inside the NBA" in caplog.text

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
            "game_id": "0022500001",
            "is_primary": True,
        },
        {
            **_post("t3_receipt", "Trade rumor", _EVENING_ET, None),
            "post_type": OTHER,
            "game_id": None,
            "is_primary": False,
        },
        {
            **_post("t3_noise", "Highlight", _EVENING_ET, "Highlight"),
            "post_type": OTHER,
            "game_id": None,
            "is_primary": False,
        },
    ]
    RECEIPTS = pl.DataFrame({"link_id": ["t3_receipt", "t3_receipt", "t3_missing"]})

    def _write_bridge(
        self, ref_dir, rows=None, *, season=None, games_fetched_at="2026-09-12"
    ):
        stamps = {
            "season": season or get_active_season(),
            "processed_at": "2026-09-13",
            "games_fetched_at": games_fetched_at,
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
        points at, and nothing else."""
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

    def test_fetch_date_mismatch_warns(self, tmp_path, caplog):
        """Verify a bridge derived from another game-log fetch is flagged."""
        self._write_bridge(tmp_path, games_fetched_at="2026-09-01")

        with caplog.at_level(logging.WARNING, logger="pipeline.posts"):
            load_posts_table(tmp_path, _games(self.GAMES), "2026-09-12", self.RECEIPTS)

        assert "2026-09-01" in caplog.text and "2026-09-12" in caplog.text

    def test_season_stamp_mismatch_warns(self, tmp_path, caplog):
        """Verify a bridge built for another season is read, not silently."""
        self._write_bridge(tmp_path, season="1999-00")

        with caplog.at_level(logging.WARNING, logger="pipeline.posts"):
            load_posts_table(tmp_path, _games(self.GAMES), "2026-09-12", self.RECEIPTS)

        assert "1999-00" in caplog.text
