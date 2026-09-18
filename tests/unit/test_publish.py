"""
Tests for pipeline/publish.py: the manifest-driven dashboard drop.
"""

import hashlib
import json
from pathlib import Path

import boto3
import polars as pl
import pytest
from botocore.stub import Stubber

from pipeline.publish import (
    MANIFEST_CACHE_CONTROL,
    MANIFEST_CONTENT_TYPE,
    MULTIPART_THRESHOLD_BYTES,
    PARQUET_CACHE_CONTROL,
    PARQUET_CONTENT_TYPE,
    LocalObject,
    PublishError,
    PublishPlan,
    build_plan,
    build_upload_set,
    execute_plan,
    list_remote,
    season_prefix,
)
from pipeline.schemas import SCHEMA_VERSION
from utils.constants import MANIFEST_FILENAME

SEASON = "2025-26"
PREFIX = "data"
BUCKET = "bucket"
KEY_PREFIX = "data/season=2025-26/"


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


def _object(name: str, body: bytes = b"x") -> LocalObject:
    """A LocalObject under the season prefix with the md5 of its body."""
    is_manifest = name == MANIFEST_FILENAME
    return LocalObject(
        key=KEY_PREFIX + name,
        path=Path(name),
        body=body,
        md5=hashlib.md5(body).hexdigest(),
        content_type=MANIFEST_CONTENT_TYPE if is_manifest else PARQUET_CONTENT_TYPE,
        cache_control=MANIFEST_CACHE_CONTROL if is_manifest else PARQUET_CACHE_CONTROL,
    )


@pytest.fixture
def s3():
    """A real S3 client with every call stubbed; unexpected calls raise."""
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="stub",
        aws_secret_access_key="stub",
    )
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def _listing(objects: list[LocalObject], **extra) -> dict:
    """A list_objects_v2 page for the given objects, ETags quoted as S3 does."""
    return {
        "Contents": [
            {"Key": o.key, "ETag": f'"{o.md5}"', "Size": len(o.body)} for o in objects
        ],
        "IsTruncated": False,
        **extra,
    }


class TestListRemote:
    """Tests for list_remote, the bucket-side state of the season prefix."""

    def test_returns_unquoted_etags_by_key(self, s3):
        """Keys map to bare hex ETags, comparable to a LocalObject's md5."""
        client, stubber = s3
        a, b = _object("a.parquet", b"aaa"), _object("b.parquet", b"bbb")
        stubber.add_response(
            "list_objects_v2",
            _listing([a, b]),
            {"Bucket": BUCKET, "Prefix": KEY_PREFIX},
        )

        remote = list_remote(client, BUCKET, KEY_PREFIX)

        assert remote == {a.key: a.md5, b.key: b.md5}

    def test_follows_continuation_tokens(self, s3):
        """Every page is read, not just the first."""
        client, stubber = s3
        a, b = _object("a.parquet", b"aaa"), _object("b.parquet", b"bbb")
        stubber.add_response(
            "list_objects_v2",
            _listing([a], IsTruncated=True, NextContinuationToken="t1"),
            {"Bucket": BUCKET, "Prefix": KEY_PREFIX},
        )
        stubber.add_response(
            "list_objects_v2",
            _listing([b]),
            {"Bucket": BUCKET, "Prefix": KEY_PREFIX, "ContinuationToken": "t1"},
        )

        remote = list_remote(client, BUCKET, KEY_PREFIX)

        assert set(remote) == {a.key, b.key}

    def test_empty_prefix(self, s3):
        """A never-published season lists as nothing."""
        client, stubber = s3
        stubber.add_response(
            "list_objects_v2",
            {"IsTruncated": False},
            {"Bucket": BUCKET, "Prefix": KEY_PREFIX},
        )

        assert list_remote(client, BUCKET, KEY_PREFIX) == {}


class TestBuildPlan:
    """Tests for build_plan, the pure diff of local against remote."""

    def test_empty_bucket_uploads_everything(self):
        """First publish: every object uploads, nothing skips or deletes."""
        local = [_object("a.parquet"), _object(MANIFEST_FILENAME)]

        plan = build_plan(local, {})

        assert plan.upload == tuple(local)
        assert plan.skip == ()
        assert plan.delete == ()

    def test_unchanged_objects_skip(self):
        """An object whose md5 equals the remote ETag is not re-uploaded."""
        a, m = _object("a.parquet", b"same"), _object(MANIFEST_FILENAME, b"new")
        remote = {a.key: a.md5, m.key: hashlib.md5(b"old").hexdigest()}

        plan = build_plan([a, m], remote)

        assert plan.skip == (a,)
        assert plan.upload == (m,)

    def test_stale_remote_keys_delete(self):
        """Keys under the prefix that the registry no longer names are removed."""
        a = _object("a.parquet")
        remote = {a.key: a.md5, KEY_PREFIX + "old_name.parquet": "abc"}

        plan = build_plan([a], remote)

        assert plan.delete == (KEY_PREFIX + "old_name.parquet",)

    def test_upload_order_is_preserved(self):
        """The manifest stays last in the upload list."""
        local = [_object("a.parquet"), _object("b.parquet"), _object(MANIFEST_FILENAME)]

        plan = build_plan(local, {})

        assert plan.upload[-1].key.endswith(MANIFEST_FILENAME)

    def test_describe_counts_each_action(self):
        """The log line says how many of each, for the dry run to read."""
        a, b = _object("a.parquet", b"same"), _object("b.parquet", b"new")
        remote = {a.key: a.md5, KEY_PREFIX + "stale.parquet": "x"}

        text = build_plan([a, b], remote).describe()

        assert "1 upload" in text
        assert "1 skip" in text
        assert "1 delete" in text
        assert "stale.parquet" in text


class TestExecutePlan:
    """Tests for execute_plan against a stubbed S3 client."""

    def test_puts_in_plan_order_with_headers_then_deletes(self, s3):
        """Uploads happen in plan order with per-object headers; the manifest
        is the last PUT; stale keys are deleted after it."""
        client, stubber = s3
        a, m = _object("a.parquet", b"aaa"), _object(MANIFEST_FILENAME, b"{}")
        plan = PublishPlan(upload=(a, m), skip=(), delete=(KEY_PREFIX + "old",))
        for o in (a, m):
            stubber.add_response(
                "put_object",
                {"ETag": f'"{o.md5}"'},
                {
                    "Bucket": BUCKET,
                    "Key": o.key,
                    "Body": o.body,
                    "ContentType": o.content_type,
                    "CacheControl": o.cache_control,
                },
            )
        stubber.add_response(
            "delete_objects",
            {"Deleted": [{"Key": KEY_PREFIX + "old"}]},
            {
                "Bucket": BUCKET,
                "Delete": {"Objects": [{"Key": KEY_PREFIX + "old"}], "Quiet": True},
            },
        )

        execute_plan(client, BUCKET, plan)

    def test_nothing_to_delete_makes_no_delete_call(self, s3):
        """An empty delete list never calls delete_objects."""
        client, stubber = s3
        a = _object("a.parquet")
        stubber.add_response(
            "put_object",
            {"ETag": f'"{a.md5}"'},
            {
                "Bucket": BUCKET,
                "Key": a.key,
                "Body": a.body,
                "ContentType": a.content_type,
                "CacheControl": a.cache_control,
            },
        )

        execute_plan(client, BUCKET, PublishPlan(upload=(a,), skip=(), delete=()))

    def test_etag_mismatch_aborts(self, s3):
        """S3 confirming a different ETag than the local md5 is a failed write."""
        client, stubber = s3
        a = _object("a.parquet", b"aaa")
        stubber.add_response("put_object", {"ETag": '"not-the-md5"'})

        with pytest.raises(PublishError, match="ETag"):
            execute_plan(client, BUCKET, PublishPlan(upload=(a,), skip=(), delete=()))

    def test_delete_errors_abort(self, s3):
        """A per-key delete error in the response is not swallowed."""
        client, stubber = s3
        stubber.add_response(
            "delete_objects",
            {"Errors": [{"Key": KEY_PREFIX + "old", "Code": "AccessDenied"}]},
        )

        with pytest.raises(PublishError, match="AccessDenied"):
            execute_plan(
                client,
                BUCKET,
                PublishPlan(upload=(), skip=(), delete=(KEY_PREFIX + "old",)),
            )
