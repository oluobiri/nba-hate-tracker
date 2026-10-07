"""
Tests for the method-example curation loader.

method_examples.yaml is validated for shape here: season, list, entry
keys, known slots, non-empty ids, no repeats. Fit against the fact is
pipeline/method_examples.py's job.
"""

import re

import pytest
import yaml

from utils.method_examples_config import (
    SLOTS,
    MethodExampleSpec,
    load_method_examples_config,
    load_method_examples_config_version,
)


@pytest.fixture
def cold_caches():
    """Clear both loaders' caches before and after the test."""
    load_method_examples_config.cache_clear()
    load_method_examples_config_version.cache_clear()
    yield
    load_method_examples_config.cache_clear()
    load_method_examples_config_version.cache_clear()


@pytest.fixture
def examples_file(tmp_path, monkeypatch, cold_caches):
    """Point the loader at a tmp method_examples.yaml; returns a writer of documents."""
    path = tmp_path / "method_examples.yaml"
    monkeypatch.setattr(
        "utils.method_examples_config._get_method_examples_path", lambda: path
    )
    monkeypatch.setattr(
        "utils.method_examples_config.get_active_season", lambda: "2025-26"
    )

    def _write(document: str | dict) -> None:
        text = document if isinstance(document, str) else yaml.safe_dump(document)
        path.write_text(text)

    return _write


def _document(examples: list, season: str = "2025-26", version: str = "1.0") -> dict:
    return {"version": version, "season": season, "examples": examples}


class TestLoadMethodExamplesConfig:
    """Shape validation and page order."""

    def test_entries_in_file_order(self, examples_file):
        """Entries come back as MethodExampleSpec in the order written: the page order."""
        examples_file(
            _document(
                [
                    {"slot": "trace", "comment_id": "aaa111"},
                    {"slot": "read", "comment_id": "bbb222"},
                ]
            )
        )

        assert load_method_examples_config() == (
            MethodExampleSpec("trace", "aaa111"),
            MethodExampleSpec("read", "bbb222"),
        )

    def test_empty_list_curates_nothing(self, examples_file):
        """A season with no examples carries the file with an empty list."""
        examples_file(_document([]))

        assert load_method_examples_config() == ()

    def test_caching_returns_same_object(self, examples_file):
        """Repeated calls return the cached tuple."""
        examples_file(_document([]))

        assert load_method_examples_config() is load_method_examples_config()

    def test_missing_file_raises(self, examples_file):
        """No method_examples.yaml for the season fails loudly."""
        with pytest.raises(FileNotFoundError):
            load_method_examples_config()

    def test_season_must_match_the_directory(self, examples_file):
        """A file copied between seasons is caught by its season key."""
        examples_file(_document([], season="2024-25"))

        with pytest.raises(ValueError, match="config/2025-26/method_examples.yaml"):
            load_method_examples_config()

    def test_examples_must_be_a_list(self, examples_file):
        """A missing or mapping-valued 'examples' key is a shape error."""
        examples_file({"version": "1.0", "season": "2025-26"})

        with pytest.raises(ValueError, match="must be a list"):
            load_method_examples_config()

    def test_entry_keys_are_exactly_slot_and_comment_id(self, examples_file):
        """An extra or missing key on an entry is refused, naming the entry."""
        examples_file(
            _document([{"slot": "trace", "comment_id": "aaa111", "why": "clear"}])
        )

        with pytest.raises(ValueError, match="entry 0 must have exactly"):
            load_method_examples_config()

    def test_unknown_slot_raises(self, examples_file):
        """A slot the page has no section for is refused, listing the slots."""
        examples_file(_document([{"slot": "funnel", "comment_id": "aaa111"}]))

        with pytest.raises(ValueError, match="slot must be one of trace, case"):
            load_method_examples_config()

    def test_empty_comment_id_raises(self, examples_file):
        """A comment_id is the key into the fact; empty is not one."""
        examples_file(_document([{"slot": "trace", "comment_id": ""}]))

        with pytest.raises(ValueError, match="non-empty"):
            load_method_examples_config()

    def test_repeated_comment_id_raises(self, examples_file):
        """One comment fills one slot; a repeat even across slots is refused."""
        examples_file(
            _document(
                [
                    {"slot": "trace", "comment_id": "aaa111"},
                    {"slot": "read", "comment_id": "aaa111"},
                ]
            )
        )

        with pytest.raises(ValueError, match="entry 1 repeats aaa111"):
            load_method_examples_config()

    def test_slots_are_the_page_sections(self):
        """The slot vocabulary is pinned: the page's sections key on it."""
        assert SLOTS == ("trace", "case", "read", "slip", "quote_check")


class TestLoadMethodExamplesConfigVersion:
    """The lineage version stamped into method_examples.parquet."""

    def test_returns_version_string(self, cold_caches):
        """Version is a MAJOR.MINOR string (format pinned, not the value)."""
        assert re.fullmatch(r"\d+\.\d+", load_method_examples_config_version())

    def test_missing_version_raises(self, examples_file):
        """A file without a version key raises ValueError with context."""
        examples_file({"season": "2025-26", "examples": []})

        with pytest.raises(ValueError, match="version"):
            load_method_examples_config_version()

    def test_unquoted_version_raises(self, examples_file):
        """An unquoted version parses as a float and would mis-stamp lineage."""
        examples_file("version: 1.10\nseason: '2025-26'\nexamples: []\n")

        with pytest.raises(ValueError, match="quoted string"):
            load_method_examples_config_version()


class TestCommittedFiles:
    """The curation on disk, both seasons."""

    def test_2025_26_loads(self, cold_caches):
        """The active season's file parses; its entries are checked at build."""
        specs = load_method_examples_config()

        assert all(spec.slot in SLOTS for spec in specs)

    def test_2024_25_curates_nothing(self, season_override):
        """The archived season carries the file for a uniform registry."""
        season_override("2024-25")

        assert load_method_examples_config() == ()
        assert re.fullmatch(r"\d+\.\d+", load_method_examples_config_version())
