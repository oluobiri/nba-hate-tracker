"""Tests for utils.formatting module."""

import pytest

from utils.formatting import format_duration, format_size


class TestFormatDuration:
    """Tests for format_duration function."""

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, "0.0s"),
            (0.0, "0.0s"),
            (45.2, "45.2s"),
            (59.9, "59.9s"),
        ],
    )
    def test_sub_minute_values(self, seconds: float, expected: str):
        """Verify sub-60 second values format with one decimal."""
        assert format_duration(seconds) == expected

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (60, "1m 0s"),
            (61, "1m 1s"),
            (90, "1m 30s"),
            (125, "2m 5s"),
            (3599, "59m 59s"),
        ],
    )
    def test_minute_values(self, seconds: float, expected: str):
        """Verify minute-range values format as Xm Ys."""
        assert format_duration(seconds) == expected

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (3600, "1h 0m 0s"),
            (3661, "1h 1m 1s"),
            (7325, "2h 2m 5s"),
            (90000, "25h 0m 0s"),
        ],
    )
    def test_hour_values(self, seconds: float, expected: str):
        """Verify hour-range values format as Xh Ym Zs."""
        assert format_duration(seconds) == expected

    def test_float_precision_preserved(self):
        """Verify float input works correctly."""
        result = format_duration(45.123)
        assert result == "45.1s"


class TestFormatSize:
    """Tests for format_size function."""

    @pytest.mark.parametrize(
        "size_bytes,expected",
        [
            (0, "0.0 B"),
            (1, "1.0 B"),
            (512, "512.0 B"),
            (1023, "1023.0 B"),
        ],
    )
    def test_byte_values(self, size_bytes: int, expected: str):
        """Verify byte-range values stay in bytes."""
        assert format_size(size_bytes) == expected

    @pytest.mark.parametrize(
        "size_bytes,expected",
        [
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (1048575, "1024.0 KB"),
        ],
    )
    def test_kilobyte_values(self, size_bytes: int, expected: str):
        """Verify KB-range values."""
        assert format_size(size_bytes) == expected

    @pytest.mark.parametrize(
        "size_bytes,expected",
        [
            (1048576, "1.0 MB"),
            (1572864, "1.5 MB"),
            (1073741823, "1024.0 MB"),
        ],
    )
    def test_megabyte_values(self, size_bytes: int, expected: str):
        """Verify MB-range values."""
        assert format_size(size_bytes) == expected

    @pytest.mark.parametrize(
        "size_bytes,expected",
        [
            (1073741824, "1.0 GB"),
            (1610612736, "1.5 GB"),
        ],
    )
    def test_gigabyte_values(self, size_bytes: int, expected: str):
        """Verify GB-range values."""
        assert format_size(size_bytes) == expected

    def test_terabyte_values(self):
        """Verify TB-range values."""
        one_tb = 1024**4
        assert format_size(one_tb) == "1.0 TB"
        assert format_size(int(1.5 * one_tb)) == "1.5 TB"
