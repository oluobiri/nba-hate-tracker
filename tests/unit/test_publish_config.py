"""
Tests for publish target loading from config/publish.yaml.
"""

import pytest

from utils.publish_config import PublishTarget, load_publish_config


class TestLoadPublishConfig:
    """Tests for load_publish_config function."""

    @pytest.fixture
    def cold_cache(self):
        """Clear the loader's cache before and after the test.

        The invalid-config tests monkeypatch the config path; a warm
        cache would return the committed target and never consult the
        patched path.
        """
        load_publish_config.cache_clear()
        yield
        load_publish_config.cache_clear()

    def test_returns_publish_target(self):
        """The committed config loads into a fully populated target."""
        target = load_publish_config()

        assert isinstance(target, PublishTarget)
        assert target.bucket == "courtsentiment-data"
        assert target.prefix == "data"
        assert target.media_prefix == "media"
        assert target.distribution_id
        assert target.base_url.startswith("https://")
        assert not target.base_url.endswith("/")
        assert target.profile

    def test_caching_returns_same_object(self):
        """Multiple calls return the same cached object."""
        result1 = load_publish_config()
        result2 = load_publish_config()
        assert result1 is result2

    def test_missing_key_raises(self, tmp_path, monkeypatch, cold_cache):
        """A config missing a required key raises ValueError naming it."""
        config_path = tmp_path / "publish.yaml"
        config_path.write_text("bucket: b\nprefix: data\n")
        monkeypatch.setattr("utils.publish_config.CONFIG_PATH", config_path)

        with pytest.raises(ValueError, match="distribution_id"):
            load_publish_config()

    def test_missing_media_prefix_raises(self, tmp_path, monkeypatch, cold_cache):
        """The media prefix is required: the media drop has no other home."""
        config_path = tmp_path / "publish.yaml"
        config_path.write_text(
            "bucket: b\nprefix: data\ndistribution_id: E1\n"
            "base_url: https://example.com\nprofile: p\n"
        )
        monkeypatch.setattr("utils.publish_config.CONFIG_PATH", config_path)

        with pytest.raises(ValueError, match="media_prefix"):
            load_publish_config()

    def test_trailing_slash_on_base_url_raises(self, tmp_path, monkeypatch, cold_cache):
        """A base_url with a trailing slash raises: keys join with one slash."""
        config_path = tmp_path / "publish.yaml"
        config_path.write_text(
            "bucket: b\nprefix: data\nmedia_prefix: media\ndistribution_id: E1\n"
            "base_url: https://example.com/\nprofile: p\n"
        )
        monkeypatch.setattr("utils.publish_config.CONFIG_PATH", config_path)

        with pytest.raises(ValueError, match="base_url"):
            load_publish_config()
