"""
Tests for pipeline/publish.py: the manifest-driven dashboard drop.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import polars as pl
import pytest
import requests
from botocore.stub import ANY, Stubber

from pipeline.media import expected_media_names
from pipeline.publish import (
    MANIFEST_CACHE_CONTROL,
    MANIFEST_CONTENT_TYPE,
    MEDIA_CACHE_CONTROL,
    MEDIA_CONTENT_TYPES,
    MULTIPART_THRESHOLD_BYTES,
    PARQUET_CACHE_CONTROL,
    PARQUET_CONTENT_TYPE,
    LocalObject,
    PublishError,
    PublishPlan,
    build_media_upload_set,
    build_plan,
    build_upload_set,
    dimension_ids,
    execute_plan,
    invalidate,
    list_remote,
    media_key_prefix,
    publish_media,
    publish_season,
    season_prefix,
    verify_public_media,
    verify_public_manifest,
)
from pipeline.schemas import SCHEMA_VERSION
from utils.constants import MANIFEST_FILENAME
from utils.publish_config import PublishTarget

SEASON = "2025-26"
PREFIX = "data"
BUCKET = "bucket"
KEY_PREFIX = "data/season=2025-26/"
DISTRIBUTION = "E1EXAMPLE"
BASE_URL = "https://example.com"
TARGET = PublishTarget(
    bucket=BUCKET,
    prefix=PREFIX,
    media_prefix="media",
    distribution_id=DISTRIBUTION,
    base_url=BASE_URL,
    profile="unused",
)


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
            {},
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


def _invalidation(status: str, key_prefix: str = KEY_PREFIX) -> dict:
    """An Invalidation block as CloudFront returns it."""
    return {
        "Id": "I1EXAMPLE",
        "Status": status,
        "CreateTime": datetime(2026, 9, 18, tzinfo=timezone.utc),
        "InvalidationBatch": {
            "Paths": {"Quantity": 1, "Items": [f"/{key_prefix}*"]},
            "CallerReference": "ref",
        },
    }


def _stub_invalidation(
    stubber: Stubber, *statuses: str, key_prefix: str = KEY_PREFIX
) -> None:
    """Expect one create_invalidation, then a get_invalidation per status."""
    stubber.add_response(
        "create_invalidation",
        {"Location": "loc", "Invalidation": _invalidation("InProgress", key_prefix)},
        {
            "DistributionId": DISTRIBUTION,
            "InvalidationBatch": {
                "Paths": {"Quantity": 1, "Items": [f"/{key_prefix}*"]},
                "CallerReference": ANY,
            },
        },
    )
    for status in statuses:
        stubber.add_response(
            "get_invalidation",
            {"Invalidation": _invalidation(status)},
            {"DistributionId": DISTRIBUTION, "Id": "I1EXAMPLE"},
        )


def _http_get(generated_at: str, status: int = 200) -> Mock:
    """A requests.get stand-in serving a public manifest."""
    response = Mock()
    response.status_code = status
    response.json.return_value = {"generated_at": generated_at}
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    return Mock(return_value=response)


class TestInvalidate:
    """Tests for invalidate, the edge flush after a drop."""

    def test_invalidates_the_season_path_and_waits(self, cloudfront):
        """One wildcard path under the season prefix; returns once completed."""
        client, stubber = cloudfront
        _stub_invalidation(stubber, "Completed")

        assert invalidate(client, DISTRIBUTION, KEY_PREFIX) == "I1EXAMPLE"

    def test_polls_until_completed(self, cloudfront, monkeypatch):
        """An in-progress invalidation is polled, not declared done."""
        client, stubber = cloudfront
        _stub_invalidation(stubber, "InProgress", "Completed")
        monkeypatch.setattr("pipeline.publish.INVALIDATION_POLL_SECONDS", 0)

        invalidate(client, DISTRIBUTION, KEY_PREFIX)

    def test_waiter_timeout_is_a_publish_error(self, cloudfront, monkeypatch):
        """Running out of polls after the writes landed reports as a
        PublishError that says so, not a raw botocore error."""
        client, stubber = cloudfront
        _stub_invalidation(stubber, "InProgress", "InProgress")
        monkeypatch.setattr("pipeline.publish.INVALIDATION_POLL_SECONDS", 0)
        monkeypatch.setattr("pipeline.publish.INVALIDATION_MAX_ATTEMPTS", 2)

        with pytest.raises(PublishError, match="written") as exc:
            invalidate(client, DISTRIBUTION, KEY_PREFIX)
        assert exc.value.__cause__ is not None


class TestVerifyPublicManifest:
    """Tests for verify_public_manifest, the drop's public confirmation."""

    def test_fetches_the_public_manifest_url(self):
        """The URL is base_url + key prefix + manifest.json."""
        http_get = _http_get("2026-09-16T12:00:00+00:00")

        verify_public_manifest(
            BASE_URL, KEY_PREFIX, "2026-09-16T12:00:00+00:00", http_get=http_get
        )

        url = http_get.call_args.args[0]
        assert url == f"{BASE_URL}/{KEY_PREFIX}manifest.json"

    def test_generated_at_mismatch_aborts(self):
        """A public manifest from another build means the drop is not done."""
        http_get = _http_get("2026-01-01T00:00:00+00:00")

        with pytest.raises(PublishError, match="generated_at") as exc:
            verify_public_manifest(
                BASE_URL, KEY_PREFIX, "2026-09-16T12:00:00+00:00", http_get=http_get
            )
        assert "2026-01-01" in str(exc.value)
        assert "2026-09-16" in str(exc.value)

    def test_http_error_aborts(self):
        """A non-2xx public response is a failed drop, chained from the cause."""
        http_get = _http_get("x", status=404)

        with pytest.raises(PublishError, match="manifest.json") as exc:
            verify_public_manifest(BASE_URL, KEY_PREFIX, "x", http_get=http_get)
        assert exc.value.__cause__ is not None


class TestPublishSeason:
    """Tests for publish_season, the run end to end."""

    def test_dry_run_lists_and_writes_nothing(self, dashboard_dir, s3, cloudfront):
        """A dry run reads the bucket and returns the plan; any write would
        hit an unstubbed call and fail the test."""
        s3_client, s3_stub = s3
        cf_client, _ = cloudfront
        s3_stub.add_response(
            "list_objects_v2",
            {"IsTruncated": False},
            {"Bucket": BUCKET, "Prefix": KEY_PREFIX},
        )

        plan = publish_season(
            dashboard_dir,
            SEASON,
            TARGET,
            s3_client,
            cf_client,
            dry_run=True,
            http_get=Mock(side_effect=AssertionError("no HTTP in a dry run")),
        )

        assert len(plan.upload) == 3
        assert plan.delete == ()

    def test_real_run_uploads_invalidates_and_verifies(
        self, dashboard_dir, manifest, s3, cloudfront
    ):
        """Tables, manifest, invalidation, then the public assert."""
        s3_client, s3_stub = s3
        cf_client, cf_stub = cloudfront
        _, objects = build_upload_set(dashboard_dir, SEASON, PREFIX)
        s3_stub.add_response(
            "list_objects_v2",
            {"IsTruncated": False},
            {"Bucket": BUCKET, "Prefix": KEY_PREFIX},
        )
        for o in objects:
            s3_stub.add_response(
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
        _stub_invalidation(cf_stub, "Completed")
        http_get = _http_get(manifest["generated_at"])

        plan = publish_season(
            dashboard_dir,
            SEASON,
            TARGET,
            s3_client,
            cf_client,
            dry_run=False,
            http_get=http_get,
        )

        assert plan.upload == tuple(objects)
        http_get.assert_called_once()

    def test_unchanged_run_verifies_without_invalidating(
        self, dashboard_dir, manifest, s3, cloudfront
    ):
        """When every object already matches, no PUT, no invalidation (any
        CloudFront call would hit an unstubbed response), but still verify."""
        s3_client, s3_stub = s3
        cf_client, _ = cloudfront
        _, objects = build_upload_set(dashboard_dir, SEASON, PREFIX)
        s3_stub.add_response(
            "list_objects_v2",
            _listing(objects),
            {"Bucket": BUCKET, "Prefix": KEY_PREFIX},
        )
        http_get = _http_get(manifest["generated_at"])

        plan = publish_season(
            dashboard_dir,
            SEASON,
            TARGET,
            s3_client,
            cf_client,
            dry_run=False,
            http_get=http_get,
        )

        assert plan.upload == ()
        assert plan.skip == tuple(objects)
        http_get.assert_called_once()

    def test_pre_flight_failure_touches_nothing(self, dashboard_dir, s3, cloudfront):
        """A failed check aborts before the bucket is even listed."""
        s3_client, _ = s3
        cf_client, _ = cloudfront
        (dashboard_dir / "teams.parquet").unlink()

        with pytest.raises(PublishError):
            publish_season(
                dashboard_dir, SEASON, TARGET, s3_client, cf_client, dry_run=False
            )


# -----------------------------------------------------------------------------
# The media drop
# -----------------------------------------------------------------------------

MEDIA_KEY_PREFIX = "media/"
SEASON_IDS = {"2024-25": ([1], [10]), "2025-26": ([1, 2], [10, 11])}


def _write_dimensions(
    dashboard_dir: Path, player_ids: list[int], team_ids: list[int]
) -> None:
    """Write the two dimension parquets the media set derives from."""
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"player_id": player_ids, "x": player_ids}).write_parquet(
        dashboard_dir / "players.parquet"
    )
    pl.DataFrame({"team_id": team_ids, "x": team_ids}).write_parquet(
        dashboard_dir / "teams.parquet"
    )


@pytest.fixture
def dashboard_dirs(tmp_path) -> list[Path]:
    """Two seasons' dashboard dirs; the older one's ids are a subset of the newer."""
    dirs = []
    for season, (player_ids, team_ids) in SEASON_IDS.items():
        d = tmp_path / season / "dashboard"
        _write_dimensions(d, player_ids, team_ids)
        dirs.append(d)
    return dirs


@pytest.fixture
def media_dir(tmp_path) -> Path:
    """Every expected media file for the two seasons' ids, plus two strays."""
    d = tmp_path / "media"
    for name in expected_media_names([1, 2], [10, 11]):
        path = d / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    (d / "headshots" / "999.png").write_bytes(b"not in any dimension")
    (d / "logos" / "notes.txt").write_text("stray")
    return d


def _http_head(failures: dict[str, tuple[int, str]] | None = None) -> Mock:
    """A requests.head stand-in: 200 with the right type unless the URL is in failures."""
    failures = failures or {}

    def head(url: str, **_) -> Mock:
        status, content_type = failures.get(
            url, (200, MEDIA_CONTENT_TYPES[Path(url).suffix])
        )
        return Mock(status_code=status, headers={"Content-Type": content_type})

    return Mock(side_effect=head)


def _put_stub(stubber: Stubber, objects: list[LocalObject]) -> None:
    """Expect one put_object per object, in order, with its headers."""
    for o in objects:
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


class TestMediaKeyPrefix:
    """Tests for media_key_prefix, the one spelling of the media prefix."""

    def test_trailing_slash(self):
        """The prefix is listed and invalidated with a trailing slash."""
        assert media_key_prefix("media") == "media/"


class TestDimensionIds:
    """Tests for dimension_ids, the union of every season's dimension tables."""

    def test_unions_across_seasons(self, dashboard_dirs):
        """Ids are the sorted union, without duplicates."""
        assert dimension_ids(dashboard_dirs) == ([1, 2], [10, 11])

    def test_dir_without_tables_is_skipped(self, dashboard_dirs, tmp_path):
        """A season with no dashboard yet contributes nothing."""
        empty = tmp_path / "2026-27" / "dashboard"
        empty.mkdir(parents=True)
        assert dimension_ids([*dashboard_dirs, empty]) == ([1, 2], [10, 11])

    def test_half_built_dir_aborts(self, dashboard_dirs):
        """One dimension without the other is a half-built season, not a subset."""
        (dashboard_dirs[0] / "teams.parquet").unlink()
        with pytest.raises(PublishError, match="teams.parquet"):
            dimension_ids(dashboard_dirs)

    def test_no_contributing_dir_aborts(self, tmp_path):
        """An empty union would plan deleting every media key; refuse it."""
        with pytest.raises(PublishError, match="no dashboard"):
            dimension_ids([tmp_path / "nothing"])

    def test_present_but_empty_tables_abort(self, tmp_path):
        """Tables with no rows are the same empty union, and the same refusal."""
        d = tmp_path / "2026-27" / "dashboard"
        _write_dimensions(d, [], [])
        with pytest.raises(PublishError, match="no dashboard"):
            dimension_ids([d])

    def test_null_id_aborts_by_name(self, tmp_path):
        """A null id is a broken table, named, not a TypeError from sorting."""
        d = tmp_path / "2026-27" / "dashboard"
        d.mkdir(parents=True)
        pl.DataFrame({"player_id": [1, None], "x": [1, 2]}).write_parquet(
            d / "players.parquet"
        )
        pl.DataFrame({"team_id": [10], "x": [1]}).write_parquet(d / "teams.parquet")
        with pytest.raises(PublishError, match="players.parquet") as exc:
            dimension_ids([d])
        assert "null" in str(exc.value)


class TestBuildMediaUploadSet:
    """Tests for build_media_upload_set, the dimension-derived allowlist."""

    def test_set_is_the_expected_names_only(self, media_dir, dashboard_dirs):
        """Keys are exactly media/ + every expected name; strays never ship."""
        objects = build_media_upload_set(media_dir, dashboard_dirs, "media")
        expected = [
            MEDIA_KEY_PREFIX + n for n in expected_media_names([1, 2], [10, 11])
        ]
        assert [o.key for o in objects] == expected
        assert not any("999" in o.key or "notes" in o.key for o in objects)

    def test_headers_by_extension(self, media_dir, dashboard_dirs):
        """Each format gets its Content-Type; one cache policy for all."""
        objects = build_media_upload_set(media_dir, dashboard_dirs, "media")
        by_suffix = {o.path.suffix: o.content_type for o in objects}
        assert by_suffix == {
            ".png": "image/png",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }
        assert {o.cache_control for o in objects} == {MEDIA_CACHE_CONTROL}
        assert MEDIA_CACHE_CONTROL == "public, max-age=604800"

    def test_body_and_md5_are_the_file_bytes(self, media_dir, dashboard_dirs):
        """The upload is the file's bytes, with the md5 S3 will echo as the ETag."""
        o = build_media_upload_set(media_dir, dashboard_dirs, "media")[0]
        assert o.body == o.path.read_bytes()
        assert o.md5 == hashlib.md5(o.body).hexdigest()

    def test_missing_files_are_listed_together(self, media_dir, dashboard_dirs):
        """Every missing file is named in one error, before anything is built."""
        (media_dir / "headshots" / "2-420.webp").unlink()
        (media_dir / "logos" / "11.svg").unlink()
        with pytest.raises(PublishError, match="2 media files") as exc:
            build_media_upload_set(media_dir, dashboard_dirs, "media")
        assert "headshots/2-420.webp" in str(exc.value)
        assert "logos/11.svg" in str(exc.value)

    def test_oversize_file_aborts(self, media_dir, dashboard_dirs, monkeypatch):
        """A file at the single-PUT threshold is refused, as for the tables."""
        monkeypatch.setattr("pipeline.publish.MULTIPART_THRESHOLD_BYTES", 8)
        with pytest.raises(PublishError, match="bytes"):
            build_media_upload_set(media_dir, dashboard_dirs, "media")


class TestVerifyPublicMedia:
    """Tests for verify_public_media, the HEAD of every key after a drop."""

    def test_heads_every_key_through_the_base_url(self, media_dir, dashboard_dirs):
        """One HEAD per object at base_url/key; nothing raised when all pass."""
        objects = build_media_upload_set(media_dir, dashboard_dirs, "media")
        http_head = _http_head()

        verify_public_media(BASE_URL, objects, http_head=http_head)

        urls = [c.args[0] for c in http_head.call_args_list]
        assert urls == [f"{BASE_URL}/{o.key}" for o in objects]

    def test_status_and_type_failures_are_collected(self, media_dir, dashboard_dirs):
        """A 404 and a wrong Content-Type are reported together, once."""
        objects = build_media_upload_set(media_dir, dashboard_dirs, "media")
        failures = {
            f"{BASE_URL}/media/headshots/1.png": (404, "text/html"),
            f"{BASE_URL}/media/logos/10.svg": (200, "text/html"),
        }
        with pytest.raises(PublishError, match="2 of") as exc:
            verify_public_media(BASE_URL, objects, http_head=_http_head(failures))
        assert "headshots/1.png: HTTP 404" in str(exc.value)
        assert "logos/10.svg: Content-Type" in str(exc.value)

    def test_content_type_parameters_are_ignored(self, media_dir, dashboard_dirs):
        """image/svg+xml; charset=utf-8 is still image/svg+xml."""
        objects = [
            o
            for o in build_media_upload_set(media_dir, dashboard_dirs, "media")
            if o.path.suffix == ".svg"
        ]
        failures = {
            f"{BASE_URL}/{o.key}": (200, "image/svg+xml; charset=utf-8")
            for o in objects
        }
        verify_public_media(BASE_URL, objects, http_head=_http_head(failures))

    def test_request_exception_is_a_failure(self, media_dir, dashboard_dirs):
        """A connection error on one URL is collected, not raised bare."""
        objects = build_media_upload_set(media_dir, dashboard_dirs, "media")[:2]
        http_head = Mock(
            side_effect=[
                requests.ConnectionError("reset"),
                Mock(
                    status_code=200, headers={"Content-Type": objects[1].content_type}
                ),
            ]
        )
        with pytest.raises(PublishError, match="1 of 2") as exc:
            verify_public_media(BASE_URL, objects, http_head=http_head)
        assert "ConnectionError" in str(exc.value)


class TestPublishMedia:
    """Tests for publish_media, the media drop end to end."""

    def _list_stub(self, stubber: Stubber, listing: dict) -> None:
        stubber.add_response(
            "list_objects_v2", listing, {"Bucket": BUCKET, "Prefix": MEDIA_KEY_PREFIX}
        )

    def test_dry_run_lists_and_writes_nothing(
        self, media_dir, dashboard_dirs, s3, cloudfront
    ):
        """A dry run reads the bucket and returns the plan; any write or HEAD fails."""
        s3_client, s3_stub = s3
        cf_client, _ = cloudfront
        self._list_stub(s3_stub, {"IsTruncated": False})

        plan = publish_media(
            media_dir,
            dashboard_dirs,
            TARGET,
            s3_client,
            cf_client,
            dry_run=True,
            http_head=Mock(side_effect=AssertionError("no HTTP in a dry run")),
        )

        assert len(plan.upload) == len(expected_media_names([1, 2], [10, 11]))
        assert plan.delete == ()

    def test_real_run_uploads_invalidates_and_verifies(
        self, media_dir, dashboard_dirs, s3, cloudfront
    ):
        """Every object, the media invalidation, then a HEAD per object."""
        s3_client, s3_stub = s3
        cf_client, cf_stub = cloudfront
        objects = build_media_upload_set(media_dir, dashboard_dirs, "media")
        self._list_stub(s3_stub, {"IsTruncated": False})
        _put_stub(s3_stub, objects)
        _stub_invalidation(cf_stub, "Completed", key_prefix=MEDIA_KEY_PREFIX)
        http_head = _http_head()

        plan = publish_media(
            media_dir,
            dashboard_dirs,
            TARGET,
            s3_client,
            cf_client,
            dry_run=False,
            http_head=http_head,
        )

        assert plan.upload == tuple(objects)
        assert http_head.call_count == len(objects)

    def test_stale_keys_delete_after_the_uploads(
        self, media_dir, dashboard_dirs, s3, cloudfront
    ):
        """A key under media/ the set no longer names is deleted, then invalidated."""
        s3_client, s3_stub = s3
        cf_client, cf_stub = cloudfront
        objects = build_media_upload_set(media_dir, dashboard_dirs, "media")
        stale = LocalObject(
            key=MEDIA_KEY_PREFIX + "headshots/999.png",
            path=Path("999.png"),
            body=b"old",
            md5=hashlib.md5(b"old").hexdigest(),
            content_type="image/png",
            cache_control=MEDIA_CACHE_CONTROL,
        )
        self._list_stub(s3_stub, _listing([*objects, stale]))
        s3_stub.add_response(
            "delete_objects",
            {},
            {
                "Bucket": BUCKET,
                "Delete": {"Objects": [{"Key": stale.key}], "Quiet": True},
            },
        )
        _stub_invalidation(cf_stub, "Completed", key_prefix=MEDIA_KEY_PREFIX)

        plan = publish_media(
            media_dir,
            dashboard_dirs,
            TARGET,
            s3_client,
            cf_client,
            dry_run=False,
            http_head=_http_head(),
        )

        assert plan.upload == ()
        assert plan.delete == (stale.key,)

    def test_unchanged_run_verifies_without_invalidating(
        self, media_dir, dashboard_dirs, s3, cloudfront
    ):
        """Every ETag matches: no PUT, no invalidation, but every key is still HEADed."""
        s3_client, s3_stub = s3
        cf_client, _ = cloudfront
        objects = build_media_upload_set(media_dir, dashboard_dirs, "media")
        self._list_stub(s3_stub, _listing(objects))
        http_head = _http_head()

        plan = publish_media(
            media_dir,
            dashboard_dirs,
            TARGET,
            s3_client,
            cf_client,
            dry_run=False,
            http_head=http_head,
        )

        assert plan.skip == tuple(objects)
        assert http_head.call_count == len(objects)

    def test_pre_flight_failure_touches_nothing(
        self, media_dir, dashboard_dirs, s3, cloudfront
    ):
        """A missing file aborts before the bucket is even listed."""
        s3_client, _ = s3
        cf_client, _ = cloudfront
        (media_dir / "logos" / "10.svg").unlink()

        with pytest.raises(PublishError, match="logos/10.svg"):
            publish_media(
                media_dir, dashboard_dirs, TARGET, s3_client, cf_client, dry_run=False
            )

    def test_verification_failure_surfaces_after_the_writes(
        self, media_dir, dashboard_dirs, s3, cloudfront
    ):
        """The writes and the invalidation ran (every stub consumed); the HEAD failure is the error."""
        s3_client, s3_stub = s3
        cf_client, cf_stub = cloudfront
        objects = build_media_upload_set(media_dir, dashboard_dirs, "media")
        self._list_stub(s3_stub, {"IsTruncated": False})
        _put_stub(s3_stub, objects)
        _stub_invalidation(cf_stub, "Completed", key_prefix=MEDIA_KEY_PREFIX)
        failures = {f"{BASE_URL}/media/logos/11.svg": (404, "text/html")}

        with pytest.raises(PublishError, match="logos/11.svg"):
            publish_media(
                media_dir,
                dashboard_dirs,
                TARGET,
                s3_client,
                cf_client,
                dry_run=False,
                http_head=_http_head(failures),
            )
