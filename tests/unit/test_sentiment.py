"""Tests for pipeline.sentiment (the sentiment classifier's identity)."""

import hashlib

import pytest

from pipeline.sentiment import (
    PROMPT_TEMPLATE,
    PROMPT_VERSION,
    SENTIMENT_STAGE,
    build_prompt,
    parse_response,
)


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


class TestPromptVersionPin:
    """Tests pinning PROMPT_VERSION to the frozen template text."""

    def test_template_hash_matches_labeled_version(self):
        """Verify the template's sha256 matches the pin for PROMPT_VERSION.

        Any template edit is a new classifier: it requires a new
        PROMPT_VERSION label, a new pinned hash, and a re-baselined
        eval suite (tests/eval/cases.yaml floors are pinned to this text).
        """
        assert PROMPT_VERSION == "v2-production+s-hint"
        assert (
            hashlib.sha256(PROMPT_TEMPLATE.encode()).hexdigest()
            == "2ae50c6125a9eb177967edf5fbddd07bc0f3b6431972686756408d82d29fd0ed"
        )

    def test_build_prompt_renders_template_exactly(self):
        """Verify build_prompt output is byte-identical to the frozen render.

        Guards the template-extraction refactor: the rendered prompt must
        match what the pre-extraction f-string produced, byte for byte.
        """
        expected = (
            "Classify sentiment toward NBA players.\n"
            "Slang: nasty/sick/filthy=positive, washed/brick/fraud/cooked=negative,"
            " GOAT=positive.\n"
            'A trailing "/s" tags the comment as sarcasm.\n'
            "\n"
            "Comment: test body\n"
            "\n"
            'Respond ONLY with JSON: {"s":"pos|neg|neu","c":0.0-1.0,'
            '"p":"Player Name"|null}'
        )

        assert build_prompt("test body") == expected


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

    @pytest.mark.parametrize(
        "raw_response,expected_p,expected_p_raw",
        [
            (
                '{"s": "neg", "c": 0.85, "p": ["Keldon Johnson"]}',
                "Keldon Johnson",
                ["Keldon Johnson"],
            ),
            (
                '{"s": "neg", "c": 0.85, "p": ["Julian", "Keldon"]}',
                None,
                ["Julian", "Keldon"],
            ),
            ('{"s": "neu", "c": 0.5, "p": []}', None, []),
            ('{"s": "neg", "c": 0.85, "p": [42]}', None, [42]),
        ],
    )
    def test_list_valued_p_normalized(
        self,
        raw_response: str,
        expected_p: str | None,
        expected_p_raw: list,
    ):
        """Verify list-valued p unwraps singleton strings, nulls the rest (#71).

        Every list shape must set p_raw so the caller can log and count
        the normalization — including unwrapped singletons.
        """
        result = parse_response(raw_response)

        assert result["p"] == expected_p
        assert result["p_raw"] == expected_p_raw

    def test_non_list_p_has_no_p_raw(self):
        """Verify a normal string p leaves the success dict unmarked."""
        result = parse_response('{"s": "pos", "c": 0.9, "p": "LeBron James"}')

        assert result == {"s": "pos", "c": 0.9, "p": "LeBron James"}

    @pytest.mark.parametrize(
        "raw_c",
        ['"high"', '["0.9"]', '{"value": 0.9}', '"0.9.1"'],
    )
    def test_non_numeric_c_reads_zero(self, raw_c: str):
        """Verify a non-numeric c degrades to 0.0 without invalidating the label (#94).

        A bad confidence must not turn a usable label into an error row.
        """
        result = parse_response(f'{{"s": "neg", "c": {raw_c}, "p": "LeBron James"}}')

        assert result == {"s": "neg", "c": 0.0, "p": "LeBron James"}


class TestSentimentStage:
    """The stage instance carries the module's identity."""

    def test_stage_names_this_classifier(self):
        """Verify the stage's identity fields match the module constants."""
        assert SENTIMENT_STAGE.name == "sentiment"
        assert SENTIMENT_STAGE.prompt_version == PROMPT_VERSION
        assert SENTIMENT_STAGE.prompt_template == PROMPT_TEMPLATE
        assert SENTIMENT_STAGE.build_prompt is build_prompt
        assert SENTIMENT_STAGE.parse_response is parse_response
        assert SENTIMENT_STAGE.sampling_params == {"temperature": 0.0}
