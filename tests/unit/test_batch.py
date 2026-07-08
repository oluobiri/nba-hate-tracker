"""Tests for pipeline.batch module."""

import json

import pytest

from pipeline.batch import (
    DEFAULT_MAX_RETRIES,
    MAX_TOKENS,
    MODEL,
    TEMPERATURE,
    backoff_delay,
    build_prompt,
    calculate_cost,
    format_batch_request,
    get_downloadable_batches,
    get_exhausted_batches,
    get_pending_batches,
    get_retryable_batches,
    init_state,
    is_wholesale_failure,
    load_state,
    mark_batch_failed,
    new_batch_entry,
    new_failed_entry,
    parse_response,
    record_retry_attempt,
    save_state,
)


def _submit_result(batch_id: str = "msgbatch_abc") -> dict:
    """Build a submit_batch-shaped result dict for state helpers."""
    return {
        "batch_id": batch_id,
        "processing_status": "in_progress",
        "request_counts": {
            "processing": 100,
            "succeeded": 0,
            "errored": 0,
            "canceled": 0,
            "expired": 0,
        },
        "ended_at": None,
        "results_url": None,
    }


def _ended_counts(succeeded: int, errored: int = 0, expired: int = 0) -> dict:
    """Build request_counts for an ended batch."""
    return {
        "processing": 0,
        "succeeded": succeeded,
        "errored": errored,
        "canceled": 0,
        "expired": expired,
    }


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


class TestGetPendingBatches:
    """Tests for get_pending_batches function."""

    def test_returns_batches_not_ended(self):
        """Verify batches with status other than 'ended' are pending."""
        state = init_state()
        state["batches"] = [
            {"batch_num": 1, "status": "in_progress"},
            {"batch_num": 2, "status": "ended"},
            {"batch_num": 3, "status": "canceling"},
        ]

        pending = get_pending_batches(state)

        assert [b["batch_num"] for b in pending] == [1, 3]

    def test_excludes_failed_batches(self):
        """Verify terminally failed entries are never polled as pending."""
        state = init_state()
        state["batches"] = [
            {"batch_num": 1, "status": "failed", "batch_id": None, "failed": True},
            {"batch_num": 2, "status": "in_progress"},
        ]

        pending = get_pending_batches(state)

        assert [b["batch_num"] for b in pending] == [2]

    def test_empty_when_all_ended(self):
        """Verify no batches are pending when all have ended."""
        state = init_state()
        state["batches"] = [
            {"batch_num": 1, "status": "ended"},
            {"batch_num": 2, "status": "ended"},
        ]

        assert get_pending_batches(state) == []

    def test_empty_state(self):
        """Verify empty state yields no pending batches."""
        assert get_pending_batches(init_state()) == []


class TestGetDownloadableBatches:
    """Tests for get_downloadable_batches function."""

    def test_returns_ended_not_downloaded(self):
        """Verify ended batches with successes and no download are returned."""
        state = init_state()
        state["batches"] = [
            {
                "batch_num": 1,
                "status": "ended",
                "results_downloaded": False,
                "request_counts": _ended_counts(succeeded=100),
            },
            {
                "batch_num": 2,
                "status": "ended",
                "results_downloaded": True,
                "request_counts": _ended_counts(succeeded=100),
            },
            {"batch_num": 3, "status": "in_progress", "results_downloaded": False},
        ]

        downloadable = get_downloadable_batches(state)

        assert [b["batch_num"] for b in downloadable] == [1]

    def test_skips_retryable_wholesale_failure(self):
        """Verify a zero-success batch awaiting retry is not downloaded."""
        state = init_state()
        state["batches"] = [
            {
                "batch_num": 1,
                "status": "ended",
                "results_downloaded": False,
                "request_counts": _ended_counts(succeeded=0, errored=100),
            }
        ]

        assert get_downloadable_batches(state) == []

    def test_includes_terminally_failed_batch(self):
        """Verify a failed batch is downloadable so errored rows are captured."""
        state = init_state()
        state["batches"] = [
            {
                "batch_num": 1,
                "status": "ended",
                "results_downloaded": False,
                "request_counts": _ended_counts(succeeded=0, errored=100),
                "failed": True,
            }
        ]

        downloadable = get_downloadable_batches(state)

        assert [b["batch_num"] for b in downloadable] == [1]

    def test_missing_downloaded_flag_treated_as_not_downloaded(self):
        """Verify a batch without results_downloaded is downloadable."""
        state = init_state()
        state["batches"] = [
            {
                "batch_num": 1,
                "status": "ended",
                "request_counts": _ended_counts(succeeded=50),
            }
        ]

        downloadable = get_downloadable_batches(state)

        assert [b["batch_num"] for b in downloadable] == [1]

    def test_empty_state(self):
        """Verify empty state yields no downloadable batches."""
        assert get_downloadable_batches(init_state()) == []


class TestIsWholesaleFailure:
    """Tests for is_wholesale_failure function."""

    def test_ended_with_zero_succeeded(self):
        """Verify an ended batch with no successes is a wholesale failure."""
        batch = {
            "status": "ended",
            "request_counts": _ended_counts(succeeded=0, errored=90, expired=10),
        }

        assert is_wholesale_failure(batch) is True

    def test_partial_failure_is_not_wholesale(self):
        """Verify an ended batch with any successes is not a wholesale failure."""
        batch = {
            "status": "ended",
            "request_counts": _ended_counts(succeeded=1, errored=99),
        }

        assert is_wholesale_failure(batch) is False

    def test_in_progress_is_not_wholesale(self):
        """Verify a still-processing batch is not a wholesale failure."""
        batch = {
            "status": "in_progress",
            "request_counts": _ended_counts(succeeded=0),
        }

        assert is_wholesale_failure(batch) is False

    def test_missing_request_counts_is_not_wholesale(self):
        """Verify an ended batch without counts is not treated as failed."""
        batch = {"status": "ended"}

        assert is_wholesale_failure(batch) is False


class TestGetRetryableBatches:
    """Tests for get_retryable_batches function."""

    def test_includes_wholesale_failure_under_cap(self):
        """Verify a zero-success batch below the retry cap is retryable."""
        state = init_state()
        state["batches"] = [
            {
                "batch_num": 1,
                "status": "ended",
                "request_counts": _ended_counts(succeeded=0, errored=100),
                "retry_count": 1,
            }
        ]

        retryable = get_retryable_batches(state, max_retries=3)

        assert [b["batch_num"] for b in retryable] == [1]

    def test_excludes_batch_at_retry_cap(self):
        """Verify a batch that consumed all retries is not retryable."""
        state = init_state()
        state["batches"] = [
            {
                "batch_num": 1,
                "status": "ended",
                "request_counts": _ended_counts(succeeded=0, errored=100),
                "retry_count": 3,
            }
        ]

        assert get_retryable_batches(state, max_retries=3) == []

    def test_excludes_failed_batch(self):
        """Verify a terminally failed batch is not retryable."""
        state = init_state()
        state["batches"] = [
            {
                "batch_num": 1,
                "status": "ended",
                "request_counts": _ended_counts(succeeded=0, errored=100),
                "retry_count": 0,
                "failed": True,
            }
        ]

        assert get_retryable_batches(state, max_retries=3) == []

    def test_excludes_partial_failure(self):
        """Verify a batch with some successes is never retried."""
        state = init_state()
        state["batches"] = [
            {
                "batch_num": 1,
                "status": "ended",
                "request_counts": _ended_counts(succeeded=99_000, errored=1_000),
            }
        ]

        assert get_retryable_batches(state, max_retries=3) == []

    def test_v1_entry_without_retry_fields(self):
        """Verify a pre-retry-schema entry is treated as retry_count zero."""
        state = init_state()
        state["batches"] = [
            {
                "batch_num": 1,
                "status": "ended",
                "request_counts": _ended_counts(succeeded=0, errored=100),
            }
        ]

        retryable = get_retryable_batches(state, max_retries=3)

        assert [b["batch_num"] for b in retryable] == [1]


class TestGetExhaustedBatches:
    """Tests for get_exhausted_batches function."""

    def test_includes_marked_failed(self):
        """Verify explicitly failed batches are exhausted."""
        state = init_state()
        state["batches"] = [{"batch_num": 1, "status": "failed", "failed": True}]

        exhausted = get_exhausted_batches(state, max_retries=3)

        assert [b["batch_num"] for b in exhausted] == [1]

    def test_includes_wholesale_failure_at_cap(self):
        """Verify a zero-success batch at the retry cap is exhausted."""
        state = init_state()
        state["batches"] = [
            {
                "batch_num": 1,
                "status": "ended",
                "request_counts": _ended_counts(succeeded=0, errored=100),
                "retry_count": 3,
            }
        ]

        exhausted = get_exhausted_batches(state, max_retries=3)

        assert [b["batch_num"] for b in exhausted] == [1]

    def test_empty_for_healthy_state(self):
        """Verify successful and in-flight batches are not exhausted."""
        state = init_state()
        state["batches"] = [
            {
                "batch_num": 1,
                "status": "ended",
                "request_counts": _ended_counts(succeeded=100),
            },
            {"batch_num": 2, "status": "in_progress"},
        ]

        assert get_exhausted_batches(state, max_retries=3) == []


class TestMarkBatchFailed:
    """Tests for mark_batch_failed function."""

    def test_sets_failed_flag(self):
        """Verify the terminal failed flag is set in place."""
        batch = {"batch_num": 1, "status": "ended"}

        mark_batch_failed(batch)

        assert batch["failed"] is True


class TestNewBatchEntry:
    """Tests for new_batch_entry function."""

    def test_builds_entry_with_retry_and_cost_fields(self):
        """Verify a fresh entry carries the full v2 schema."""
        entry = new_batch_entry(
            batch_num=1,
            request_file="batch_001.jsonl",
            submit_result=_submit_result("msgbatch_new"),
            submitted_at="2026-07-08T00:00:00+00:00",
            estimated_cost_usd=1.25,
        )

        assert entry["batch_num"] == 1
        assert entry["batch_id"] == "msgbatch_new"
        assert entry["request_file"] == "batch_001.jsonl"
        assert entry["status"] == "in_progress"
        assert entry["results_downloaded"] is False
        assert entry["retry_count"] == 0
        assert entry["superseded_batch_ids"] == []
        assert entry["failed"] is False
        assert entry["estimated_cost_usd"] == 1.25
        assert entry["actual_input_tokens"] == 0
        assert entry["actual_output_tokens"] == 0
        assert entry["actual_cost_usd"] == 0.0


class TestNewFailedEntry:
    """Tests for new_failed_entry function."""

    def test_builds_terminal_entry(self):
        """Verify a submission-never-succeeded entry is terminal."""
        entry = new_failed_entry(
            batch_num=2,
            request_file="batch_002.jsonl",
            attempted_at="2026-07-08T00:00:00+00:00",
            retry_count=3,
        )

        assert entry["batch_id"] is None
        assert entry["status"] == "failed"
        assert entry["failed"] is True
        assert entry["retry_count"] == 3

    def test_terminal_entry_is_exhausted_not_pending(self):
        """Verify the entry trips fail-fast and never enters the poll loop."""
        state = init_state()
        state["batches"] = [
            new_failed_entry(
                batch_num=2,
                request_file="batch_002.jsonl",
                attempted_at="2026-07-08T00:00:00+00:00",
                retry_count=3,
            )
        ]

        assert get_pending_batches(state) == []
        assert len(get_exhausted_batches(state, max_retries=3)) == 1


class TestRecordRetryAttempt:
    """Tests for record_retry_attempt function."""

    def test_successful_retry_after_one_failure(self):
        """Verify a wholesale-failed batch retried once becomes healthy.

        Issue #29 required scenario: batch fails wholesale, is retried,
        and the retry succeeds.
        """
        # Arrange: first attempt ended with zero successes
        batch = new_batch_entry(
            batch_num=1,
            request_file="batch_001.jsonl",
            submit_result=_submit_result("msgbatch_old"),
            submitted_at="2026-07-08T00:00:00+00:00",
            estimated_cost_usd=1.25,
        )
        batch["status"] = "ended"
        batch["request_counts"] = _ended_counts(succeeded=0, errored=100)
        state = init_state()
        state["batches"] = [batch]
        assert len(get_retryable_batches(state, max_retries=3)) == 1

        # Act: resubmit
        record_retry_attempt(
            batch,
            submit_result=_submit_result("msgbatch_retry"),
            submitted_at="2026-07-08T01:00:00+00:00",
            estimated_cost_usd=1.25,
        )

        # Assert: attempt is swapped in and tracked
        assert batch["batch_id"] == "msgbatch_retry"
        assert batch["retry_count"] == 1
        assert batch["superseded_batch_ids"] == ["msgbatch_old"]
        assert batch["results_downloaded"] is False
        assert get_retryable_batches(state, max_retries=3) == []
        assert [b["batch_num"] for b in get_pending_batches(state)] == [1]

        # Retry completes with successes: downloadable, not retryable
        batch["status"] = "ended"
        batch["request_counts"] = _ended_counts(succeeded=100)
        assert get_retryable_batches(state, max_retries=3) == []
        assert [b["batch_num"] for b in get_downloadable_batches(state)] == [1]

    def test_terminal_failure_after_max_retries(self):
        """Verify a batch failing every retry becomes exhausted, not retryable.

        Issue #29 required scenario: retries exhausted, batch marked failed.
        """
        batch = new_batch_entry(
            batch_num=1,
            request_file="batch_001.jsonl",
            submit_result=_submit_result("msgbatch_0"),
            submitted_at="2026-07-08T00:00:00+00:00",
            estimated_cost_usd=1.25,
        )
        state = init_state()
        state["batches"] = [batch]

        for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
            batch["status"] = "ended"
            batch["request_counts"] = _ended_counts(succeeded=0, errored=100)
            record_retry_attempt(
                batch,
                submit_result=_submit_result(f"msgbatch_{attempt}"),
                submitted_at="2026-07-08T01:00:00+00:00",
                estimated_cost_usd=1.25,
            )

        batch["status"] = "ended"
        batch["request_counts"] = _ended_counts(succeeded=0, errored=100)

        assert batch["retry_count"] == DEFAULT_MAX_RETRIES
        assert batch["superseded_batch_ids"] == [
            "msgbatch_0",
            "msgbatch_1",
            "msgbatch_2",
        ]
        assert get_retryable_batches(state, max_retries=DEFAULT_MAX_RETRIES) == []
        exhausted = get_exhausted_batches(state, max_retries=DEFAULT_MAX_RETRIES)
        assert [b["batch_num"] for b in exhausted] == [1]

        mark_batch_failed(batch)
        assert batch["failed"] is True

    def test_resets_actual_cost_fields(self):
        """Verify a retry zeroes any actuals from the superseded attempt."""
        batch = new_batch_entry(
            batch_num=1,
            request_file="batch_001.jsonl",
            submit_result=_submit_result("msgbatch_old"),
            submitted_at="2026-07-08T00:00:00+00:00",
            estimated_cost_usd=1.25,
        )
        batch["actual_input_tokens"] = 999
        batch["actual_output_tokens"] = 111
        batch["actual_cost_usd"] = 0.42

        record_retry_attempt(
            batch,
            submit_result=_submit_result("msgbatch_retry"),
            submitted_at="2026-07-08T01:00:00+00:00",
            estimated_cost_usd=1.25,
        )

        assert batch["actual_input_tokens"] == 0
        assert batch["actual_output_tokens"] == 0
        assert batch["actual_cost_usd"] == 0.0

    def test_v1_entry_without_retry_fields(self):
        """Verify retrying a pre-retry-schema entry initializes tracking."""
        batch = {
            "batch_num": 1,
            "batch_id": "msgbatch_v1",
            "request_file": "batch_001.jsonl",
            "status": "ended",
            "request_counts": _ended_counts(succeeded=0, errored=100),
            "results_downloaded": True,
        }

        record_retry_attempt(
            batch,
            submit_result=_submit_result("msgbatch_retry"),
            submitted_at="2026-07-08T01:00:00+00:00",
            estimated_cost_usd=1.25,
        )

        assert batch["retry_count"] == 1
        assert batch["superseded_batch_ids"] == ["msgbatch_v1"]
        assert batch["results_downloaded"] is False


class TestBackoffDelay:
    """Tests for backoff_delay function."""

    @pytest.mark.parametrize(
        "attempt,expected",
        [
            (0, 2.0),
            (1, 4.0),
            (2, 8.0),
            (3, 16.0),
        ],
    )
    def test_exponential_growth(self, attempt: int, expected: float):
        """Verify delay doubles with each attempt."""
        assert backoff_delay(attempt) == expected

    def test_respects_cap(self):
        """Verify delay never exceeds the cap."""
        assert backoff_delay(10) == 60.0

    def test_custom_base_and_cap(self):
        """Verify base and cap parameters are honored."""
        assert backoff_delay(0, base=1.0, cap=5.0) == 1.0
        assert backoff_delay(4, base=1.0, cap=5.0) == 5.0


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
