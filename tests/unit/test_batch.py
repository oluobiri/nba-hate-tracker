"""Tests for pipeline.batch module."""

import json

import pytest

from pipeline.batch import (
    MAX_TOKENS,
    MODEL,
    TEMPERATURE,
    build_prompt,
    calculate_cost,
    format_batch_request,
    init_state,
    load_state,
    parse_response,
    save_state,
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


class TestFormatBatchRequest:
    """Tests for format_batch_request function."""

    def test_returns_correct_structure(self, valid_nba_comment: dict):
        """Verify output has custom_id and params keys."""
        result = format_batch_request(valid_nba_comment)

        assert "custom_id" in result
        assert "params" in result
        assert result["custom_id"] == valid_nba_comment["id"]

    def test_params_has_required_fields(self, valid_nba_comment: dict):
        """Verify params contains model, max_tokens, temperature, messages."""
        result = format_batch_request(valid_nba_comment)
        params = result["params"]

        assert params["model"] == MODEL
        assert params["max_tokens"] == MAX_TOKENS
        assert params["temperature"] == TEMPERATURE
        assert "messages" in params

    def test_messages_contains_prompt(self, valid_nba_comment: dict):
        """Verify messages array has user role with prompt."""
        result = format_batch_request(valid_nba_comment)
        messages = result["params"]["messages"]

        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert valid_nba_comment["body"] in messages[0]["content"]


class TestInitState:
    """Tests for init_state function."""

    def test_returns_correct_structure(self):
        """Verify init_state returns dict with required keys."""
        state = init_state()

        assert "total_input_tokens" in state
        assert "total_output_tokens" in state
        assert "estimated_cost_usd" in state
        assert "batches" in state

        assert state["total_input_tokens"] == 0
        assert state["total_output_tokens"] == 0
        assert state["estimated_cost_usd"] == 0.0
        assert state["batches"] == []

    def test_returns_new_dict_each_call(self):
        """Verify each call returns a new dict instance."""
        state1 = init_state()
        state2 = init_state()

        assert state1 is not state2
        assert state1["batches"] is not state2["batches"]

        # Modifying one should not affect the other
        state1["batches"].append({"test": "data"})
        assert state2["batches"] == []


class TestLoadState:
    """Tests for load_state function."""

    def test_returns_empty_state_when_file_missing(self, tmp_path):
        """Verify load_state returns empty state when file doesn't exist."""
        state_path = tmp_path / "nonexistent" / "state.json"

        state = load_state(state_path)

        assert state == init_state()

    def test_loads_existing_state(self, tmp_path):
        """Verify load_state correctly loads existing JSON file."""
        state_path = tmp_path / "state.json"
        expected_state = {
            "total_input_tokens": 1000,
            "total_output_tokens": 500,
            "estimated_cost_usd": 1.25,
            "batches": [
                {
                    "batch_num": 1,
                    "batch_id": "msgbatch_123",
                    "request_file": "batch_001.jsonl",
                    "status": "ended",
                }
            ],
        }

        with open(state_path, "w") as f:
            json.dump(expected_state, f)

        state = load_state(state_path)

        assert state == expected_state

    def test_adds_missing_keys_to_corrupted_state(self, tmp_path):
        """Verify load_state adds default values for missing keys."""
        state_path = tmp_path / "state.json"
        # Simulate corrupted state file with missing keys
        corrupted_state = {
            "batches": [{"batch_id": "msgbatch_123"}],
            # Missing: total_input_tokens, total_output_tokens, estimated_cost_usd
        }

        with open(state_path, "w") as f:
            json.dump(corrupted_state, f)

        state = load_state(state_path)

        # Should have all required keys with defaults for missing ones
        assert state["batches"] == [{"batch_id": "msgbatch_123"}]
        assert state["total_input_tokens"] == 0
        assert state["total_output_tokens"] == 0
        assert state["estimated_cost_usd"] == 0.0


class TestSaveState:
    """Tests for save_state function."""

    def test_creates_file(self, tmp_path):
        """Verify save_state creates the state file."""
        state_path = tmp_path / "state.json"
        state = init_state()

        save_state(state, state_path)

        assert state_path.exists()

    def test_creates_parent_directories(self, tmp_path):
        """Verify save_state creates parent directories if missing."""
        state_path = tmp_path / "nested" / "deep" / "state.json"
        state = init_state()

        save_state(state, state_path)

        assert state_path.exists()

    def test_writes_valid_json(self, tmp_path):
        """Verify save_state writes valid, readable JSON."""
        state_path = tmp_path / "state.json"
        state = {
            "total_input_tokens": 5000,
            "total_output_tokens": 2500,
            "estimated_cost_usd": 3.75,
            "batches": [
                {"batch_id": "msgbatch_abc", "status": "in_progress"}
            ],
        }

        save_state(state, state_path)

        with open(state_path) as f:
            loaded = json.load(f)

        assert loaded == state

    def test_atomic_write_no_partial_file(self, tmp_path):
        """Verify atomic write doesn't leave partial files on success."""
        state_path = tmp_path / "state.json"
        state = init_state()

        save_state(state, state_path)

        # No .tmp files should remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_overwrites_existing_file(self, tmp_path):
        """Verify save_state overwrites existing state file."""
        state_path = tmp_path / "state.json"

        # Write initial state
        initial_state = init_state()
        initial_state["total_input_tokens"] = 100
        save_state(initial_state, state_path)

        # Write updated state
        updated_state = init_state()
        updated_state["total_input_tokens"] = 9999
        save_state(updated_state, state_path)

        with open(state_path) as f:
            loaded = json.load(f)

        assert loaded["total_input_tokens"] == 9999
