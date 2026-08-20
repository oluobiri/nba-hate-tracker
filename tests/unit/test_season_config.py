"""
Tests for season configuration loading.

Tests cover the pointer file, the per-season facts file (window,
subreddits, calendar and corpus blocks, version), the --season override
reaching every season-derived layer, and caching behavior.
"""

import re
from types import MappingProxyType

import pytest
import yaml

import pipeline.processors
from utils.paths import get_data_dir
from utils.player_config import (
    build_alias_to_player_map,
    load_player_config,
    load_player_config_version,
    load_player_metadata,
)
from utils.season_config import (
    CALENDAR_KEYS,
    CORPUS_KEYS,
    clear_season_override,
    get_active_season,
    load_season_config,
    load_season_config_version,
    load_season_pointer,
    set_season_override,
)


# A well-formed per-season facts document for the tmp-file tests.
VALID_FACTS = {
    "version": "1.0",
    "season": "2024-25",
    "start_date": "2024-10-01",
    "end_date": "2025-06-30",
    "subreddits": ["nba"],
    "calendar": {key: None for key in CALENDAR_KEYS},
    "corpus": {key: None for key in CORPUS_KEYS},
}


def _clear_season_caches() -> None:
    """Clear the season-derived config caches.

    Also resets the compiled-pattern global in pipeline.processors:
    cache_clear() bypasses the override's warm-cache guard, which
    normally subsumes that global via load_player_config().
    """
    for fn in (
        load_season_config,
        load_player_config,
        build_alias_to_player_map,
        load_player_metadata,
        load_player_config_version,
    ):
        fn.cache_clear()
    pipeline.processors._player_patterns = None


@pytest.fixture
def facts_file(tmp_path, monkeypatch):
    """Point the facts loader at a tmp season dir; yields a writer.

    The writer takes a dict (or raw YAML text), writes it as
    config/<season>/season.yaml under tmp_path, and clears the facts
    cache so the next load_season_config() reads it. The pointer file
    is untouched, so the active season is the real one.
    """
    monkeypatch.setattr("utils.season_config.CONFIG_DIR", tmp_path)
    load_season_config.cache_clear()

    def _write(doc: dict | str, season: str | None = None) -> None:
        season = season or get_active_season()
        target = tmp_path / season / "season.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        text = doc if isinstance(doc, str) else yaml.safe_dump(doc)
        target.write_text(text)
        load_season_config.cache_clear()

    yield _write
    load_season_config.cache_clear()


class TestLoadSeasonPointer:
    """Tests for load_season_pointer function (config/season.yaml)."""

    @pytest.fixture
    def pointer_file(self, tmp_path, monkeypatch):
        """Point the pointer loader at a tmp file; yields a writer."""
        path = tmp_path / "season.yaml"
        monkeypatch.setattr("utils.season_config.POINTER_PATH", path)
        load_season_pointer.cache_clear()

        def _write(text: str) -> None:
            path.write_text(text)
            load_season_pointer.cache_clear()

        yield _write
        load_season_pointer.cache_clear()

    def test_has_both_pointers(self):
        """The real pointer file carries the operational and published seasons."""
        pointers = load_season_pointer()
        assert set(pointers) == {"season", "published_season"}
        assert re.fullmatch(r"\d{4}-\d{2}", pointers["season"])
        assert re.fullmatch(r"\d{4}-\d{2}", pointers["published_season"])

    def test_pointer_file_carries_no_facts(self):
        """The pointer file is pointers only: no per-season facts leak back in."""
        with open("config/season.yaml") as f:
            raw = yaml.safe_load(f)
        assert set(raw) == {"season", "published_season"}

    def test_published_season_optional(self, pointer_file):
        """A pointer file without published_season loads with None."""
        pointer_file('season: "2025-26"\n')
        assert load_season_pointer()["published_season"] is None

    def test_missing_season_raises(self, pointer_file):
        """A pointer file without `season` fails loud."""
        pointer_file('published_season: "2024-25"\n')
        with pytest.raises(ValueError, match="'season'"):
            load_season_pointer()

    def test_malformed_pointer_raises(self, pointer_file):
        """A non-YYYY-YY pointer is rejected."""
        pointer_file('season: "2025"\n')
        with pytest.raises(ValueError, match="YYYY-YY"):
            load_season_pointer()

    def test_caching_returns_same_object(self):
        """Multiple calls return the same cached object."""
        assert load_season_pointer() is load_season_pointer()


class TestLoadSeasonConfig:
    """Tests for load_season_config function (config/<season>/season.yaml)."""

    def test_returns_dict(self):
        """Config loader returns a dict."""
        config = load_season_config()
        assert isinstance(config, dict)

    def test_has_required_keys(self):
        """Config contains the original contract keys plus the new blocks."""
        config = load_season_config()
        for key in (
            "season",
            "start_date",
            "end_date",
            "subreddits",
            "version",
            "calendar",
            "corpus",
        ):
            assert key in config

    def test_season_is_string(self):
        """Season identifier is a string."""
        config = load_season_config()
        assert isinstance(config["season"], str)

    def test_dates_are_iso_format(self):
        """Start and end dates are valid ISO date strings."""
        config = load_season_config()
        for key in ("start_date", "end_date"):
            parts = config[key].split("-")
            assert len(parts) == 3, f"{key} should be YYYY-MM-DD"
            assert len(parts[0]) == 4, f"{key} year should be 4 digits"

    def test_subreddits_is_nonempty_tuple(self):
        """Subreddits is a non-empty tuple of strings (frozen for cache safety)."""
        config = load_season_config()
        subreddits = config["subreddits"]
        assert isinstance(subreddits, tuple)
        assert len(subreddits) > 0
        for sub in subreddits:
            assert isinstance(sub, str)

    def test_season_and_dates_consistent(self):
        """Season identifier and date range agree, whatever season is active.

        Invariants instead of pinned values so a legitimate season flip
        doesn't break the suite: season is YYYY-YY, start_date falls in
        the first year, end_date in the second.
        """
        config = load_season_config()
        assert re.fullmatch(r"\d{4}-\d{2}", config["season"])
        start_year = int(config["season"][:4])
        assert config["season"][5:7] == str(start_year + 1)[-2:]
        assert config["start_date"].startswith(str(start_year))
        assert config["end_date"].startswith(str(start_year + 1))
        assert "nba" in config["subreddits"]

    def test_calendar_block_shape(self):
        """calendar is a read-only mapping over exactly CALENDAR_KEYS.

        Values are ISO date strings or None (unknown-until-knowable);
        no other type reaches callers.
        """
        calendar = load_season_config()["calendar"]
        assert isinstance(calendar, MappingProxyType)
        assert tuple(calendar) == CALENDAR_KEYS
        for value in calendar.values():
            assert value is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)

    def test_calendar_dates_fall_inside_window(self):
        """Every filled calendar date sits inside the download window.

        The window brackets the season; a calendar date outside it would
        mean either a typo or a window that doesn't cover the season.
        """
        config = load_season_config()
        for key, value in config["calendar"].items():
            if value is not None:
                assert config["start_date"] <= value <= config["end_date"], key

    def test_calendar_phase_boundaries_ordered(self):
        """The phase-boundary keys are chronological when all are filled."""
        calendar = load_season_config()["calendar"]
        boundaries = [
            calendar[k]
            for k in (
                "opening_night",
                "play_in_start",
                "playoffs_start",
                "finals_start",
                "finals_end",
            )
        ]
        if all(boundaries):
            assert boundaries == sorted(boundaries)

    def test_corpus_block_shape(self):
        """corpus is a read-only mapping over exactly CORPUS_KEYS, ints or None."""
        corpus = load_season_config()["corpus"]
        assert isinstance(corpus, MappingProxyType)
        assert tuple(corpus) == CORPUS_KEYS
        for value in corpus.values():
            assert value is None or isinstance(value, int)

    def test_version_is_quoted_string(self):
        """version is a MAJOR.MINOR string, exposed by both accessors."""
        version = load_season_config()["version"]
        assert re.fullmatch(r"\d+\.\d+", version)
        assert load_season_config_version() == version

    def test_caching_returns_same_object(self):
        """Multiple calls return the same cached object."""
        result1 = load_season_config()
        result2 = load_season_config()
        assert result1 is result2


class TestLoadSeasonConfigValidation:
    """Loader rejects malformed per-season facts files."""

    def test_missing_required_key_raises(self, facts_file):
        """A facts file without the original contract keys fails loud."""
        doc = {k: v for k, v in VALID_FACTS.items() if k != "start_date"}
        doc["season"] = get_active_season()
        facts_file(doc)
        with pytest.raises(ValueError, match="start_date"):
            load_season_config()

    def test_season_mismatch_raises(self, facts_file):
        """A facts file whose `season` disagrees with its directory fails.

        Guards the copy-a-season-dir-and-forget-to-edit mistake: the
        directory is the resolver's truth, the in-file key must agree.
        """
        facts_file({**VALID_FACTS, "season": "1999-00"})
        with pytest.raises(ValueError, match="1999-00"):
            load_season_config()

    def test_missing_version_raises(self, facts_file):
        """A facts file without a version key raises with context."""
        doc = {k: v for k, v in VALID_FACTS.items() if k != "version"}
        doc["season"] = get_active_season()
        facts_file(doc)
        with pytest.raises(ValueError, match="'version' key"):
            load_season_config()

    def test_unquoted_version_raises(self, facts_file):
        """An unquoted YAML version (parsed as float) is rejected."""
        facts_file(
            f'version: 1.10\nseason: "{get_active_season()}"\n'
            + yaml.safe_dump(
                {k: v for k, v in VALID_FACTS.items() if k not in ("version", "season")}
            )
        )
        with pytest.raises(ValueError, match="quoted string"):
            load_season_config()

    def test_missing_calendar_block_raises(self, facts_file):
        """The calendar block is part of the schema, even when all-null."""
        doc = {k: v for k, v in VALID_FACTS.items() if k != "calendar"}
        doc["season"] = get_active_season()
        facts_file(doc)
        with pytest.raises(ValueError, match="'calendar' block"):
            load_season_config()

    def test_calendar_key_set_is_exact(self, facts_file):
        """A calendar with an unknown or missing key fails.

        Write-once applies to the schema: a new key is a code change
        (CALENDAR_KEYS), not a per-file addition.
        """
        doc = {**VALID_FACTS, "season": get_active_season()}
        doc["calendar"] = {**doc["calendar"], "preseason_start": None}
        facts_file(doc)
        with pytest.raises(ValueError, match="'calendar' keys must be exactly"):
            load_season_config()

    def test_calendar_nulls_allowed(self, facts_file):
        """All-null calendar and corpus blocks load (values fill when knowable)."""
        facts_file({**VALID_FACTS, "season": get_active_season()})
        config = load_season_config()
        assert all(v is None for v in config["calendar"].values())
        assert all(v is None for v in config["corpus"].values())

    def test_unquoted_calendar_date_raises(self, facts_file):
        """An unquoted date (YAML datetime.date) is rejected.

        Calendar values are ISO strings like start_date/end_date, so
        callers see one type; YAML's native date would leak a second.
        """
        doc = {**VALID_FACTS, "season": get_active_season()}
        text = yaml.safe_dump(doc).replace(
            "opening_night: null", "opening_night: 2024-10-22"
        )
        facts_file(text)
        with pytest.raises(ValueError, match="calendar.opening_night"):
            load_season_config()

    def test_malformed_calendar_date_raises(self, facts_file):
        """A non-ISO calendar string is rejected."""
        doc = {**VALID_FACTS, "season": get_active_season()}
        doc["calendar"] = {**doc["calendar"], "christmas": "Dec 25"}
        facts_file(doc)
        with pytest.raises(ValueError, match="calendar.christmas"):
            load_season_config()

    def test_non_integer_corpus_count_raises(self, facts_file):
        """A corpus count that isn't an int is rejected."""
        doc = {**VALID_FACTS, "season": get_active_season()}
        doc["corpus"] = {"raw_comments": "7.28M"}
        facts_file(doc)
        with pytest.raises(ValueError, match="corpus.raw_comments"):
            load_season_config()


class TestGetActiveSeason:
    """Tests for get_active_season convenience function."""

    def test_returns_string(self):
        """Active season is a string."""
        season = get_active_season()
        assert isinstance(season, str)

    def test_matches_pointer(self):
        """Without an override, the active season is the pointer file's."""
        assert get_active_season() == load_season_pointer()["season"]

    def test_matches_facts_file(self):
        """The facts file loaded is the active season's."""
        assert load_season_config()["season"] == get_active_season()

    def test_matches_season_format(self):
        """Active season is a YYYY-YY identifier."""
        assert re.fullmatch(r"\d{4}-\d{2}", get_active_season())


class TestSeasonOverride:
    """Tests for the process-level --season override (#51)."""

    @pytest.fixture(autouse=True)
    def clean_override_state(self):
        """Cold season-derived caches and no override, before and after."""
        _clear_season_caches()
        clear_season_override()
        yield
        clear_season_override()
        _clear_season_caches()

    def test_override_changes_active_season(self):
        """get_active_season returns the override when set."""
        set_season_override("2024-25")
        assert get_active_season() == "2024-25"

    def test_no_override_uses_pointer_file(self):
        """Without an override, the on-disk pointer value is returned."""
        assert get_active_season() == load_season_pointer()["season"]

    def test_clear_restores_pointer_value(self):
        """Clearing the override restores the on-disk pointer value."""
        set_season_override("2024-25")
        clear_season_override()
        assert get_active_season() == load_season_pointer()["season"]

    def test_override_reaches_paths(self):
        """Path resolution honors the override with no parameter threading."""
        set_season_override("2024-25")
        assert get_data_dir().name == "2024-25"

    def test_override_reaches_player_config(self):
        """The player-config loader resolves the override season's file.

        Pins the 2024-25 config's player count — safe because that
        season is over and its config is frozen.
        """
        set_season_override("2024-25")
        players, _ = load_player_config()
        assert len(players) == 111

    def test_override_reaches_season_facts(self):
        """The facts loader resolves the override season's file.

        Pins 2024-25's window and a calendar date — frozen season, safe
        to pin. This is #51's former "known seam", now dissolved: the
        override reaches dates, not just paths.
        """
        set_season_override("2024-25")
        config = load_season_config()
        assert config["season"] == "2024-25"
        assert config["start_date"] == "2024-10-01"
        assert config["end_date"] == "2025-06-30"
        assert config["calendar"]["opening_night"] == "2024-10-22"
        assert config["corpus"]["raw_comments"] == 7_041_235

    def test_invalid_format_raises(self):
        """A malformed season identifier is rejected up front."""
        with pytest.raises(ValueError, match="YYYY-YY"):
            set_season_override("2024-2025")

    @pytest.mark.parametrize(
        "warming_call",
        [load_season_config, load_player_config, load_player_config_version],
        ids=["season_config", "player_config", "config_version"],
    )
    def test_raises_if_caches_already_warm(self, warming_call):
        """Setting the override after config loading fails loud.

        A silent cache clear could mask early code having already acted
        on the wrong season, so the guard raises instead. Every
        season-derived cache must trip it.
        """
        warming_call()
        with pytest.raises(RuntimeError, match="script entry"):
            set_season_override("2024-25")
