"""
Tests for the recap curation loader.

recaps.yaml is validated for shape here: season, list, entry keys, quoted
game ids, non-empty slugs, no repeats. Existence against the frames is
pipeline/recaps.py's job. The committed files are pinned in order, since
the order is the page order.
"""

import re

import pytest
import yaml

from utils.recaps_config import (
    RecapSpec,
    load_recaps_config,
    load_recaps_config_version,
)

TEN = (
    ("0042500317", "chet-holmgren"),
    ("0042500405", "victor-wembanyama"),
    ("0042500404", "de-aaron-fox"),
    ("0042500402", "karl-anthony-towns"),
    ("0042500312", "stephon-castle"),
    ("0042500311", "dylan-harper"),
    ("0042500301", "jalen-brunson"),
    ("0042500173", "lebron-james"),
    ("0042500164", "nikola-jokic"),
    ("0022500001", "kevin-durant"),
)


@pytest.fixture
def cold_caches():
    """Clear both loaders' caches before and after the test.

    The path-patching tests would otherwise read the real config's
    cached value and never consult the patched path.
    """
    load_recaps_config.cache_clear()
    load_recaps_config_version.cache_clear()
    yield
    load_recaps_config.cache_clear()
    load_recaps_config_version.cache_clear()


@pytest.fixture
def recaps_file(tmp_path, monkeypatch, cold_caches):
    """Point the loader at a tmp recaps.yaml; returns a writer of documents."""
    path = tmp_path / "recaps.yaml"
    monkeypatch.setattr("utils.recaps_config._get_recaps_path", lambda: path)
    monkeypatch.setattr("utils.recaps_config.get_active_season", lambda: "2025-26")

    def _write(document: str | dict) -> None:
        text = document if isinstance(document, str) else yaml.safe_dump(document)
        path.write_text(text)

    return _write


def _document(recaps: list, season: str = "2025-26", version: str = "1.0") -> dict:
    return {"version": version, "season": season, "recaps": recaps}


class TestLoadRecapsConfig:
    """Shape validation and page order."""

    def test_entries_in_file_order(self, recaps_file):
        """Entries come back as RecapSpec in the order written: the page order."""
        recaps_file(
            _document(
                [
                    {"game_id": "0042500317", "slug": "chet-holmgren"},
                    {"game_id": "0022500001", "slug": "kevin-durant"},
                ]
            )
        )

        assert load_recaps_config() == (
            RecapSpec("0042500317", "chet-holmgren"),
            RecapSpec("0022500001", "kevin-durant"),
        )

    def test_empty_list_curates_nothing(self, recaps_file):
        """A season with no recaps carries the file with an empty list."""
        recaps_file(_document([]))

        assert load_recaps_config() == ()

    def test_caching_returns_same_object(self, recaps_file):
        """Repeated calls return the cached tuple."""
        recaps_file(_document([]))

        assert load_recaps_config() is load_recaps_config()

    def test_missing_file_raises(self, recaps_file):
        """No recaps.yaml for the season fails loudly, like players.yaml."""
        with pytest.raises(FileNotFoundError):
            load_recaps_config()

    def test_season_must_match_the_directory(self, recaps_file):
        """A file copied between seasons is caught by its season key."""
        recaps_file(_document([], season="2024-25"))

        with pytest.raises(ValueError, match="config/2025-26/recaps.yaml"):
            load_recaps_config()

    def test_recaps_must_be_a_list(self, recaps_file):
        """A missing or mapping-valued 'recaps' key is a shape error."""
        recaps_file({"version": "1.0", "season": "2025-26"})

        with pytest.raises(ValueError, match="must be a list"):
            load_recaps_config()

    def test_entry_keys_are_exactly_game_id_and_slug(self, recaps_file):
        """An extra or missing key on an entry is refused, naming the entry."""
        recaps_file(
            _document(
                [{"game_id": "0042500317", "slug": "chet-holmgren", "title": "G7"}]
            )
        )

        with pytest.raises(ValueError, match="entry 0 must have exactly"):
            load_recaps_config()

    def test_unquoted_game_id_raises(self, recaps_file):
        """An unquoted id parses as a number (a leading zero as octal), so
        the loader demands a quoted 10-digit string."""
        recaps_file(
            "version: '1.0'\nseason: '2025-26'\nrecaps:\n  - {game_id: 42500317, slug: x}\n"
        )

        with pytest.raises(ValueError, match="quoted 10-digit"):
            load_recaps_config()

    def test_short_game_id_raises(self, recaps_file):
        """A quoted id still has to be the ten digits stats.nba.com uses."""
        recaps_file(_document([{"game_id": "004250031", "slug": "chet-holmgren"}]))

        with pytest.raises(ValueError, match="quoted 10-digit"):
            load_recaps_config()

    def test_empty_slug_raises(self, recaps_file):
        """A slug is the player's URL identity; empty is not one."""
        recaps_file(_document([{"game_id": "0042500317", "slug": ""}]))

        with pytest.raises(ValueError, match="non-empty"):
            load_recaps_config()

    def test_repeated_entry_raises(self, recaps_file):
        """The same game and player twice would be two files with one key."""
        recaps_file(
            _document(
                [
                    {"game_id": "0042500317", "slug": "chet-holmgren"},
                    {"game_id": "0042500317", "slug": "chet-holmgren"},
                ]
            )
        )

        with pytest.raises(ValueError, match="entry 1 repeats"):
            load_recaps_config()

    def test_same_game_two_players_is_two_recaps(self, recaps_file):
        """Only the pair is unique; a game can be replayed for two players."""
        recaps_file(
            _document(
                [
                    {"game_id": "0042500317", "slug": "chet-holmgren"},
                    {"game_id": "0042500317", "slug": "victor-wembanyama"},
                ]
            )
        )

        assert len(load_recaps_config()) == 2


class TestLoadRecapsConfigVersion:
    """The lineage version stamped into every recap file."""

    def test_returns_version_string(self, cold_caches):
        """Version is a MAJOR.MINOR string (format pinned, not the value)."""
        assert re.fullmatch(r"\d+\.\d+", load_recaps_config_version())

    def test_missing_version_raises(self, recaps_file):
        """A recaps.yaml without a version key raises ValueError with context."""
        recaps_file({"season": "2025-26", "recaps": []})

        with pytest.raises(ValueError, match="version"):
            load_recaps_config_version()

    def test_unquoted_version_raises(self, recaps_file):
        """An unquoted version parses as a float and would mis-stamp lineage."""
        recaps_file("version: 1.10\nseason: '2025-26'\nrecaps: []\n")

        with pytest.raises(ValueError, match="quoted string"):
            load_recaps_config_version()


class TestCommittedFiles:
    """The curation on disk, both seasons."""

    def test_2025_26_curates_the_ten_in_page_order(self, cold_caches):
        """The launch curation is the spike's ten, ordered for the page."""
        specs = load_recaps_config()

        assert [(s.game_id, s.slug) for s in specs] == list(TEN)

    def test_2024_25_curates_nothing(self, season_override):
        """The archived season carries the file for a uniform registry,
        with nothing curated yet."""
        season_override("2024-25")

        assert load_recaps_config() == ()
        assert re.fullmatch(r"\d+\.\d+", load_recaps_config_version())
