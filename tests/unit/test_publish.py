"""
Tests for pipeline/publish.py: the manifest-driven dashboard drop.
"""

import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from pipeline.publish import (
    MANIFEST_CACHE_CONTROL,
    MANIFEST_CONTENT_TYPE,
    MULTIPART_THRESHOLD_BYTES,
    PARQUET_CACHE_CONTROL,
    PARQUET_CONTENT_TYPE,
    PublishError,
    build_upload_set,
    season_prefix,
)
from pipeline.schemas import SCHEMA_VERSION
from utils.constants import MANIFEST_FILENAME

SEASON = "2025-26"
PREFIX = "data"


def _write_table(path: Path, rows: int, schema_version: str | None = None) -> None:
    """Write a rows-long parquet with the given schema_version stamp."""
    stamp = str(SCHEMA_VERSION) if schema_version is None else schema_version
    pl.DataFrame({"x": list(range(rows))}).write_parquet(
        path, metadata={"schema_version": stamp}
    )


def _write_manifest(dashboard_dir: Path, manifest: dict) -> None:
    """Write the manifest the way scripts/aggregate_sentiment.py does."""
    with open(dashboard_dir / MANIFEST_FILENAME, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


@pytest.fixture
def manifest() -> dict:
    """A contract-shaped manifest registering two tables."""
    return {
        "schema_version": SCHEMA_VERSION,
        "season": SEASON,
        "generated_at": "2026-09-16T12:00:00+00:00",
        "config_versions": {},
        "classifiers": {},
        "snapshots": {},
        "rules": {},
        "calendar": {},
        "corpus": {},
        "populations": {},
        "tables": {
            "player_overall": {
                "file": "player_overall.parquet",
                "rows": 3,
                "population": "attributed",
            },
            "teams": {"file": "teams.parquet", "rows": 2, "population": None},
        },
    }


@pytest.fixture
def dashboard_dir(tmp_path, manifest) -> Path:
    """A dashboard directory: the manifest, its two tables, and a stray CSV."""
    _write_table(tmp_path / "player_overall.parquet", rows=3)
    _write_table(tmp_path / "teams.parquet", rows=2)
    (tmp_path / "bar_race.csv").write_text("not,a,contract,file\n")
    _write_manifest(tmp_path, manifest)
    return tmp_path


class TestSeasonPrefix:
    """Tests for season_prefix, the one spelling of the season's key prefix."""

    def test_hive_style_under_the_prefix(self):
        """The public path is the S3 key: prefix, then season=<season>/."""
        assert season_prefix("data", "2025-26") == "data/season=2025-26/"


class TestBuildUploadSet:
    """Tests for build_upload_set, the pre-flight and the allowlist."""

    def test_upload_set_is_the_registry_plus_manifest(self, dashboard_dir):
        """Exactly the registered files ship; the stray CSV never does."""
        # Act
        _, objects = build_upload_set(dashboard_dir, SEASON, PREFIX)

        # Assert
        assert [o.key for o in objects] == [
            "data/season=2025-26/player_overall.parquet",
            "data/season=2025-26/teams.parquet",
            "data/season=2025-26/manifest.json",
        ]

    def test_manifest_is_last(self, dashboard_dir):
        """A reader never sees a new manifest over old tables."""
        _, objects = build_upload_set(dashboard_dir, SEASON, PREFIX)
        assert objects[-1].path.name == MANIFEST_FILENAME

    def test_returns_the_loaded_manifest(self, dashboard_dir, manifest):
        """The manifest the plan was built from comes back for post-flight."""
        loaded, _ = build_upload_set(dashboard_dir, SEASON, PREFIX)
        assert loaded["generated_at"] == manifest["generated_at"]

    def test_headers_per_object_type(self, dashboard_dir):
        """Parquet and manifest carry their own content type and cache policy."""
        _, objects = build_upload_set(dashboard_dir, SEASON, PREFIX)
        parquet, manifest_object = objects[0], objects[-1]

        assert parquet.content_type == PARQUET_CONTENT_TYPE
        assert parquet.cache_control == PARQUET_CACHE_CONTROL
        assert manifest_object.content_type == MANIFEST_CONTENT_TYPE
        assert manifest_object.cache_control == MANIFEST_CACHE_CONTROL

    def test_body_and_md5_are_the_file_bytes(self, dashboard_dir):
        """The md5 is of the exact bytes uploaded, so it compares to the ETag."""
        _, objects = build_upload_set(dashboard_dir, SEASON, PREFIX)
        manifest_object = objects[-1]

        expected = (dashboard_dir / MANIFEST_FILENAME).read_bytes()
        assert manifest_object.body == expected
        assert manifest_object.md5 == hashlib.md5(expected).hexdigest()

    def test_missing_manifest_aborts(self, dashboard_dir):
        """A season without a manifest cannot be published."""
        (dashboard_dir / MANIFEST_FILENAME).unlink()

        with pytest.raises(PublishError, match="manifest.json"):
            build_upload_set(dashboard_dir, SEASON, PREFIX)

    def test_season_mismatch_aborts(self, dashboard_dir):
        """The manifest's season must be the requested one."""
        with pytest.raises(PublishError, match="2024-25") as exc:
            build_upload_set(dashboard_dir, "2024-25", PREFIX)
        assert SEASON in str(exc.value)

    def test_schema_version_mismatch_aborts(self, dashboard_dir, manifest):
        """A manifest on another contract version is not publishable."""
        manifest["schema_version"] = SCHEMA_VERSION - 1
        _write_manifest(dashboard_dir, manifest)

        with pytest.raises(PublishError, match="schema_version"):
            build_upload_set(dashboard_dir, SEASON, PREFIX)

    def test_missing_registered_file_aborts(self, dashboard_dir):
        """Every registered file must exist before anything is built."""
        (dashboard_dir / "teams.parquet").unlink()

        with pytest.raises(PublishError, match="teams.parquet"):
            build_upload_set(dashboard_dir, SEASON, PREFIX)

    def test_row_count_mismatch_aborts(self, dashboard_dir):
        """The parquet's row count must equal the registry's."""
        _write_table(dashboard_dir / "teams.parquet", rows=5)

        with pytest.raises(PublishError, match="teams.parquet") as exc:
            build_upload_set(dashboard_dir, SEASON, PREFIX)
        assert "rows" in str(exc.value)

    def test_stamp_mismatch_aborts(self, dashboard_dir):
        """The parquet's schema_version stamp must match the contract."""
        _write_table(dashboard_dir / "teams.parquet", rows=2, schema_version="4")

        with pytest.raises(PublishError, match="teams.parquet") as exc:
            build_upload_set(dashboard_dir, SEASON, PREFIX)
        assert "schema_version" in str(exc.value)

    def test_oversize_file_aborts(self, dashboard_dir, monkeypatch):
        """A file at the multipart threshold is refused: its ETag would not
        be an MD5 and the skip-unchanged comparison would never match."""
        monkeypatch.setattr("pipeline.publish.MULTIPART_THRESHOLD_BYTES", 16)

        with pytest.raises(PublishError, match="player_overall.parquet") as exc:
            build_upload_set(dashboard_dir, SEASON, PREFIX)
        assert "bytes" in str(exc.value)

    def test_threshold_is_the_boto3_default(self):
        """8 MiB is where boto3's managed transfer would switch to multipart."""
        assert MULTIPART_THRESHOLD_BYTES == 8 * 1024 * 1024
