"""Tests for pipeline.batch module."""

import pytest

from pipeline.batch import build_prompt, calculate_cost, parse_response


class TestBuildPrompt:
    """Tests for build_prompt function."""

    def test_format_contains_required_elements(self, valid_nba_comment: dict):
        """Verify prompt contains classification instruction and JSON format."""
        result = build_prompt(valid_nba_comment["body"])

        assert "Classify sentiment" in result
        assert "Comment:" in result
        assert '"s":"pos|neg|neu"' in result

    def test_preserves_comment_body(self, valid_nba_comment: dict):
        """Verify comment body appears unchanged in output."""
        body = valid_nba_comment["body"]
        result = build_prompt(body)

        assert body in result

    def test_handles_special_characters(self):
        """Verify special characters in comment are preserved."""
        comment = 'Curry 3pt% is "insane" & he\'s cooking!'
        result = build_prompt(comment)

        assert comment in result

    def test_handles_empty_string(self):
        """Verify empty comment still produces valid prompt."""
        result = build_prompt("")

        assert "Classify sentiment" in result
        assert "Comment:" in result


class TestParseResponse:
    """Tests for parse_response function."""

    def test_valid_json(self, valid_sentiment_responses: list[tuple[str, dict]]):
        """Verify valid JSON responses are parsed correctly."""
        for raw_response, expected in valid_sentiment_responses:
            result = parse_response(raw_response)
            assert result == expected

    def test_markdown_wrapped(
        self, markdown_wrapped_responses: list[tuple[str, str, str | None]]
    ):
        """Verify markdown-wrapped JSON is handled correctly."""
        for raw_response, expected_s, expected_p in markdown_wrapped_responses:
            result = parse_response(raw_response)

            assert result["s"] == expected_s
            assert result["p"] == expected_p

    def test_malformed_returns_error(self, malformed_responses: list[str]):
        """Verify malformed responses return error dict with raw field."""
        for raw_response in malformed_responses:
            result = parse_response(raw_response)

            assert result["s"] == "error"
            assert result["c"] == 0.0
            assert result["p"] is None
            assert result["raw"] == raw_response

    def test_empty_string(self):
        """Verify empty string returns error dict."""
        result = parse_response("")

        assert result["s"] == "error"
        assert result["c"] == 0.0
        assert result["p"] is None
        assert "raw" in result

    def test_whitespace_only(self):
        """Verify whitespace-only input returns error dict."""
        result = parse_response("   \n\t  ")

        assert result["s"] == "error"
        assert result["c"] == 0.0
        assert result["p"] is None


class TestCalculateCost:
    """Tests for calculate_cost function."""

    def test_one_million_tokens_each(self):
        """Verify cost for 1M input + 1M output tokens."""
        # $0.50/M input + $2.50/M output = $3.00
        cost = calculate_cost(input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(3.00)

    def test_realistic_single_request(self):
        """Verify cost for a realistic single request (~150 in, ~30 out)."""
        cost = calculate_cost(input_tokens=150, output_tokens=30)

        expected = (150 / 1_000_000) * 0.50 + (30 / 1_000_000) * 2.50
        assert cost == pytest.approx(expected)

    def test_zero_tokens(self):
        """Verify zero tokens returns zero cost."""
        cost = calculate_cost(input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_only_input(self):
        """Verify cost with only input tokens."""
        cost = calculate_cost(input_tokens=1_000_000, output_tokens=0)
        assert cost == pytest.approx(0.50)

    def test_only_output(self):
        """Verify cost with only output tokens."""
        cost = calculate_cost(input_tokens=0, output_tokens=1_000_000)
        assert cost == pytest.approx(2.50)
