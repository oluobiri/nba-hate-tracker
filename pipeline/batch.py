"""Core batch processing functions for sentiment classification.

Pure functions for prompt building, response parsing, and cost calculation.
API submission functions use the Anthropic Batch API.
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

# Model configuration
MODEL = "claude-haiku-4-5-20251001"
TEMPERATURE = 0.0
MAX_TOKENS = 75
REQUESTS_PER_BATCH = 100_000

# Batch API pricing (50% discount applied)
INPUT_COST_PER_MTOK = 0.50  # $0.50 per million input tokens
OUTPUT_COST_PER_MTOK = 2.50  # $2.50 per million output tokens

# State file and batch data layout
STATE_FILENAME = "state.json"
REQUESTS_SUBDIR = "requests"
RESPONSES_SUBDIR = "responses"

# Retry configuration
DEFAULT_MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_CAP_SECONDS = 60.0


# Frozen v2 prompt (notebooks/2025-26/06_prompt_experiments): the eval
# floors and known_miss flags in tests/eval/cases.yaml are pinned to this
# exact text. Any edit is a new classifier: bump PROMPT_VERSION, re-pin
# the hash test, re-baseline the eval suite.
PROMPT_VERSION = "v2-production+s-hint"
PROMPT_TEMPLATE = """Classify sentiment toward NBA players.
Slang: nasty/sick/filthy=positive, washed/brick/fraud/cooked=negative, GOAT=positive.
A trailing "/s" tags the comment as sarcasm.

Comment: {comment_body}

Respond ONLY with JSON: {{"s":"pos|neg|neu","c":0.0-1.0,"p":"Player Name"|null}}"""


def build_prompt(comment_body: str) -> str:
    """
    Build minimal prompt for sentiment classification.

    Renders PROMPT_TEMPLATE, the frozen prompt labeled PROMPT_VERSION.

    Args:
        comment_body: The raw Reddit comment text.

    Returns:
        The formatted prompt for the model.
    """
    return PROMPT_TEMPLATE.format(comment_body=comment_body)


def parse_response(text: str) -> dict:
    """
    Parse the model response into a structured dict.

    Handles three cases:
    1. Valid JSON directly
    2. JSON wrapped in markdown code blocks
    3. Malformed responses

    Args:
        text: Raw text response from the model.

    Returns:
        Success: {"s": "pos|neg|neu", "c": float, "p": str|None}
        A rare list-valued "p" (#71) is normalized — a single-string list
        unwraps, anything else becomes None — and the original list is
        preserved under "p_raw" so callers can log the occurrence.
        Error: {"s": "error", "c": 0.0, "p": None, "raw": str}
    """
    if not text or not text.strip():
        return {"s": "error", "c": 0.0, "p": None, "raw": text}

    cleaned = text.strip()

    # Handle markdown code blocks
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]

    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]

    cleaned = cleaned.strip()

    try:
        result = json.loads(cleaned)

        #  Handle array responses (multi-player comments) - take first element
        if isinstance(result, list):
            if len(result) == 0:
                return {"s": "error", "c": 0.0, "p": None, "raw": text}
            result = result[0]

        # Validate required fields
        if "s" not in result:
            return {"s": "error", "c": 0.0, "p": None, "raw": text}

        # Normalize and validate sentiment value
        sentiment = result.get("s", "")
        if sentiment not in ("pos", "neg", "neu"):
            return {"s": "error", "c": 0.0, "p": None, "raw": text}

        parsed = {
            "s": result["s"],
            "c": float(result.get("c", 0.0)),
            "p": result.get("p"),
        }

        # Normalize rare list-valued player field (#71): unwrap a
        # single-string list, drop anything else; keep the original
        # under p_raw so callers can log the occurrence.
        if isinstance(parsed["p"], list):
            raw_list = parsed["p"]
            parsed["p_raw"] = raw_list
            parsed["p"] = (
                raw_list[0]
                if len(raw_list) == 1 and isinstance(raw_list[0], str)
                else None
            )

        return parsed
    except (json.JSONDecodeError, ValueError, TypeError):
        return {"s": "error", "c": 0.0, "p": None, "raw": text}


def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    """
    Calculate the USD cost for a batch API request.

    Args:
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Total cost in USD.
    """
    input_cost = (input_tokens / 1_000_000) * INPUT_COST_PER_MTOK
    output_cost = (output_tokens / 1_000_000) * OUTPUT_COST_PER_MTOK
    return input_cost + output_cost


def format_batch_request(comment: dict) -> dict:
    """
    Format a comment into an Anthropic Batch API request.

    Args:
        comment: Comment dict with 'id' and 'body' fields.

    Returns:
        Batch request dict with custom_id and params.
    """
    return {
        "custom_id": comment["id"],
        "params": {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "messages": [{"role": "user", "content": build_prompt(comment["body"])}],
        },
    }


# -----------------------------------------------------------------------------
# State management
# -----------------------------------------------------------------------------


def init_state() -> dict:
    """
    Return empty state structure for batch tracking.

    Returns:
        Dict with total_input_tokens, total_output_tokens,
        estimated_cost_usd, and batches list.
    """
    return {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "actual_cost_usd": 0.0,
        "batches": [],
    }


def load_state(state_path: Path) -> dict:
    """
    Load state from JSON file, or return empty state if file doesn't exist.

    Validates state has required keys, adding defaults for missing fields.

    Args:
        state_path: Path to state JSON file.

    Returns:
        State dict loaded from file, or empty state if missing.
    """
    if not state_path.exists():
        return init_state()

    with open(state_path) as f:
        state = json.load(f)

    # Ensure required keys exist (handles corrupted/edited state files)
    defaults = init_state()
    for key, default_value in defaults.items():
        if key not in state:
            state[key] = default_value

    return state


def save_state(state: dict, state_path: Path) -> None:
    """
    Save state to JSON file atomically.

    Uses tempfile + os.replace to avoid partial writes on crash.
    Cleans up temp file on failure to avoid orphaned files.

    Args:
        state: State dict to save.
        state_path: Path to write state file.
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=state_path.parent,
        suffix=".tmp",
        delete=False,
    ) as f:
        json.dump(state, f, indent=2)
        temp_path = f.name

    try:
        os.replace(temp_path, state_path)
    except Exception:
        # Clean up temp file on failure
        Path(temp_path).unlink(missing_ok=True)
        raise


def get_pending_batches(state: dict) -> list[dict]:
    """
    Get batches that haven't finished processing yet.

    Terminally failed entries are excluded — they will never end, and
    submission-failure entries carry no batch_id to poll.

    Args:
        state: Current state dict.

    Returns:
        List of batch entries with status != "ended" and not failed.
    """
    return [
        b
        for b in state.get("batches", [])
        if b.get("status") != "ended" and not b.get("failed", False)
    ]


def get_downloadable_batches(state: dict) -> list[dict]:
    """
    Get batches whose results should be downloaded.

    Retryable wholesale failures are skipped — their attempt is about to
    be superseded, so downloading would only produce a stale results file.
    Terminally failed batches ARE downloadable so their errored rows reach
    failed_requests.jsonl for manual investigation.

    Args:
        state: Current state dict.

    Returns:
        List of ended, not-yet-downloaded batch entries that either
        produced successes or are terminally failed.
    """
    return [
        b
        for b in state.get("batches", [])
        if b.get("status") == "ended"
        and not b.get("results_downloaded", False)
        and (not is_wholesale_failure(b) or b.get("failed", False))
    ]


def get_missing_results(state: dict) -> list[dict]:
    """
    Get batches whose results file is still expected but not downloaded.

    This is the build gate for sentiment.parquet: assembly must wait for
    every batch that will eventually produce a results file — including
    retryable wholesale failures (their retry will be downloaded) and
    terminally failed ended batches (their errored rows are captured).
    Submission-failure entries (no batch_id, status "failed") can never
    be downloaded and must not block the build forever.

    Args:
        state: Current state dict.

    Returns:
        List of batch entries still owing a results file.
    """
    return [
        b
        for b in state.get("batches", [])
        if not b.get("results_downloaded", False)
        and not (b.get("failed", False) and b.get("status") != "ended")
    ]


def get_unsubmitted_request_files(state: dict, requests_dir: Path) -> list[str]:
    """
    Get request files on disk that have no corresponding state entry.

    This reconciles state against the requests directory — the ground
    truth of the run's population (#71). Mid-run, state only knows about
    batches submitted so far, so the parquet build must not proceed while
    any request file is still unsubmitted. Submission-failure entries
    carry request_file too, so they correctly count as submitted.

    Args:
        state: Current state dict.
        requests_dir: Directory containing batch_NNN.jsonl request files.

    Returns:
        Sorted request filenames with no state entry. A missing or empty
        requests directory yields an empty list (the gate falls through
        to the state-based checks).
    """
    submitted = {b.get("request_file") for b in state.get("batches", [])}
    return sorted(
        f.name for f in requests_dir.glob("batch_*.jsonl") if f.name not in submitted
    )


def is_wholesale_failure(batch: dict) -> bool:
    """
    Check whether a batch ended with zero successful requests.

    Only wholesale failures are eligible for whole-batch retry; a batch
    with any successes keeps its results, and its failed rows go to
    failed_requests.jsonl instead (per-request retry is out of scope).

    Args:
        batch: Batch entry dict from state.

    Returns:
        True if the batch ended and request_counts shows no successes.
        An ended batch with missing counts is NOT treated as a failure.
    """
    if batch.get("status") != "ended":
        return False
    counts = batch.get("request_counts")
    if not counts:
        return False
    return counts.get("succeeded", 0) == 0


def get_retryable_batches(
    state: dict, max_retries: int = DEFAULT_MAX_RETRIES
) -> list[dict]:
    """
    Get wholesale-failed batches that still have retry budget.

    Args:
        state: Current state dict.
        max_retries: Maximum resubmission attempts per batch.

    Returns:
        List of batch entries eligible for resubmission.
    """
    return [
        b
        for b in state.get("batches", [])
        if is_wholesale_failure(b)
        and not b.get("failed", False)
        and b.get("retry_count", 0) < max_retries
    ]


def get_exhausted_batches(
    state: dict, max_retries: int = DEFAULT_MAX_RETRIES
) -> list[dict]:
    """
    Get batches that failed terminally or consumed their retry budget.

    Args:
        state: Current state dict.
        max_retries: Maximum resubmission attempts per batch.

    Returns:
        List of batch entries requiring manual investigation.
    """
    return [
        b
        for b in state.get("batches", [])
        if b.get("failed", False)
        or (is_wholesale_failure(b) and b.get("retry_count", 0) >= max_retries)
    ]


def mark_batch_failed(batch: dict) -> None:
    """
    Mark a batch entry as terminally failed (in place).

    Stored explicitly rather than derived so the terminal state survives
    later runs invoked with a different --max-retries value.

    Args:
        batch: Batch entry dict from state.
    """
    batch["failed"] = True


def new_batch_entry(
    batch_num: int,
    request_file: str,
    submit_result: dict,
    submitted_at: str,
    estimated_cost_usd: float,
) -> dict:
    """
    Build a state entry for a freshly submitted batch.

    Args:
        batch_num: Batch number extracted from the request filename.
        request_file: Name of the request JSONL file.
        submit_result: Dict returned by submit_batch.
        submitted_at: ISO 8601 submission timestamp.
        estimated_cost_usd: Pre-submission cost estimate for this batch.

    Returns:
        Batch entry dict with retry tracking, cost fields, and classifier
        identity (model + prompt_version, recorded at submission time)
        initialized.
    """
    return {
        "batch_num": batch_num,
        "batch_id": submit_result["batch_id"],
        "request_file": request_file,
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "status": submit_result["processing_status"],
        "submitted_at": submitted_at,
        "ended_at": submit_result["ended_at"],
        "results_url": submit_result["results_url"],
        "request_counts": submit_result["request_counts"],
        "results_downloaded": False,
        "retry_count": 0,
        "superseded_batch_ids": [],
        "failed": False,
        "estimated_cost_usd": estimated_cost_usd,
        "actual_input_tokens": 0,
        "actual_output_tokens": 0,
        "actual_cost_usd": 0.0,
    }


def new_failed_entry(
    batch_num: int,
    request_file: str,
    attempted_at: str,
    retry_count: int,
) -> dict:
    """
    Build a terminal state entry for a batch whose submission never succeeded.

    The entry has no batch_id to poll and failed=True, so it trips the
    fail-fast gate on the next run instead of being silently reattempted.

    Args:
        batch_num: Batch number extracted from the request filename.
        request_file: Name of the request JSONL file.
        attempted_at: ISO 8601 timestamp of the final failed attempt.
        retry_count: Submission attempts consumed.

    Returns:
        Terminal batch entry dict.
    """
    return {
        "batch_num": batch_num,
        "batch_id": None,
        "request_file": request_file,
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "status": "failed",
        "submitted_at": attempted_at,
        "ended_at": None,
        "results_url": None,
        "request_counts": None,
        "results_downloaded": False,
        "retry_count": retry_count,
        "superseded_batch_ids": [],
        "failed": True,
        "estimated_cost_usd": 0.0,
        "actual_input_tokens": 0,
        "actual_output_tokens": 0,
        "actual_cost_usd": 0.0,
    }


def record_retry_attempt(
    batch: dict,
    submit_result: dict,
    submitted_at: str,
    estimated_cost_usd: float,
) -> None:
    """
    Record a resubmission on an existing batch entry (in place).

    The superseded batch_id is kept for console investigation; download
    and cost fields are reset so the surviving attempt's results fully
    replace the failed attempt's.

    Args:
        batch: Batch entry dict from state.
        submit_result: Dict returned by submit_batch for the new attempt.
        submitted_at: ISO 8601 submission timestamp.
        estimated_cost_usd: Cost estimate for the resubmitted batch.
    """
    if batch.get("batch_id"):
        batch.setdefault("superseded_batch_ids", []).append(batch["batch_id"])
    batch["batch_id"] = submit_result["batch_id"]
    batch["status"] = submit_result["processing_status"]
    batch["submitted_at"] = submitted_at
    batch["ended_at"] = submit_result["ended_at"]
    batch["results_url"] = submit_result["results_url"]
    batch["request_counts"] = submit_result["request_counts"]
    batch["results_downloaded"] = False
    batch["retry_count"] = batch.get("retry_count", 0) + 1
    batch["estimated_cost_usd"] = estimated_cost_usd
    batch["actual_input_tokens"] = 0
    batch["actual_output_tokens"] = 0
    batch["actual_cost_usd"] = 0.0


def get_classifier_identity(state: dict) -> dict[str, str] | None:
    """
    Read the classifier identity recorded in state at submission.

    The identity is a birth certificate for the frozen classification
    layer: assembly stamps it into sentiment.parquet unchanged, never
    re-deriving it from live code.

    Args:
        state: Current state dict.

    Returns:
        {"model": ..., "prompt_version": ...} when every batch entry
        carries the same identity; None when no entry carries one
        (state recorded before the fields existed).

    Raises:
        ValueError: If entries disagree, or only some carry an identity.
    """
    pairs = {
        (b.get("model"), b.get("prompt_version")) for b in state.get("batches", [])
    }
    if not pairs or pairs == {(None, None)}:
        return None
    if len(pairs) > 1 or None in next(iter(pairs)):
        raise ValueError(f"Inconsistent classifier identity in state: {pairs!r}")

    model, prompt_version = next(iter(pairs))
    return {"model": model, "prompt_version": prompt_version}


def summarize_actual_usage(results: list[dict]) -> dict:
    """
    Sum actual token usage over a batch's downloaded results.

    Only succeeded rows carry usage; errored/canceled/expired rows
    contribute zero, so actual cost reflects only paid-for results.

    Args:
        results: Result dicts as returned by download_results.

    Returns:
        Dict with actual_input_tokens, actual_output_tokens, and
        actual_cost_usd, ready to merge into a batch entry.
    """
    input_tokens = sum(
        r["input_tokens"] for r in results if r["result_type"] == "succeeded"
    )
    output_tokens = sum(
        r["output_tokens"] for r in results if r["result_type"] == "succeeded"
    )
    return {
        "actual_input_tokens": input_tokens,
        "actual_output_tokens": output_tokens,
        "actual_cost_usd": calculate_cost(input_tokens, output_tokens),
    }


def compute_run_totals(state: dict) -> dict:
    """
    Compute run-level totals as sums over per-batch entries.

    Recomputed from scratch rather than incremented, so repeated calls
    (and retries that reset per-batch actuals) can never double-count.
    estimated_cost_usd reflects each batch's current attempt, not
    cumulative exposure across superseded attempts.

    Args:
        state: Current state dict.

    Returns:
        Dict with total_input_tokens, total_output_tokens,
        estimated_cost_usd, and actual_cost_usd, ready to merge into
        the state dict via state.update().
    """
    batches = state.get("batches", [])
    return {
        "total_input_tokens": sum(b.get("actual_input_tokens", 0) for b in batches),
        "total_output_tokens": sum(b.get("actual_output_tokens", 0) for b in batches),
        "estimated_cost_usd": sum(b.get("estimated_cost_usd", 0.0) for b in batches),
        "actual_cost_usd": sum(b.get("actual_cost_usd", 0.0) for b in batches),
    }


def backoff_delay(
    attempt: int,
    base: float = BACKOFF_BASE_SECONDS,
    cap: float = BACKOFF_CAP_SECONDS,
) -> float:
    """
    Compute the exponential backoff delay for a retry attempt.

    Args:
        attempt: Zero-based attempt index.
        base: Delay in seconds for the first retry.
        cap: Maximum delay in seconds.

    Returns:
        Delay in seconds, capped.
    """
    return min(base * (2**attempt), cap)


# -----------------------------------------------------------------------------
# Batch API functions
# -----------------------------------------------------------------------------


def submit_batch(request_file: Path) -> dict:
    """
    Submit a JSONL file to the Anthropic Batch API.

    Args:
        request_file: Path to JSONL file with batch requests.

    Returns:
        Dict with batch_id, processing_status, request_counts,
        ended_at, and results_url.

    Raises:
        FileNotFoundError: If request_file doesn't exist.
        RuntimeError: If API call fails.
    """
    if not request_file.exists():
        raise FileNotFoundError(f"Batch file not found: {request_file}")

    client = anthropic.Anthropic()

    try:
        with open(request_file) as f:
            requests = [json.loads(line) for line in f if line.strip()]
        batch = client.messages.batches.create(requests=requests)
    except anthropic.APIError as e:
        raise RuntimeError(
            f"Anthropic API error submitting {request_file.name}: {e}"
        ) from e

    return {
        "batch_id": batch.id,
        "processing_status": batch.processing_status,
        "request_counts": {
            "processing": batch.request_counts.processing,
            "succeeded": batch.request_counts.succeeded,
            "errored": batch.request_counts.errored,
            "canceled": batch.request_counts.canceled,
            "expired": batch.request_counts.expired,
        },
        "ended_at": batch.ended_at.isoformat() if batch.ended_at else None,
        "results_url": batch.results_url,
    }


def submit_batch_with_retry(
    request_file: Path, max_retries: int = DEFAULT_MAX_RETRIES
) -> dict:
    """
    Submit a batch file, retrying submission-time API errors with backoff.

    Backoff attempts within one call are not persisted to state; only
    full exhaustion is surfaced (the caller records terminal failure).
    The Anthropic SDK already retries transient 429/5xx internally, so
    this wraps hard submission failures.

    Args:
        request_file: Path to JSONL file with batch requests.
        max_retries: Maximum submission attempts before giving up.

    Returns:
        Dict from submit_batch (batch_id, processing_status, ...).

    Raises:
        FileNotFoundError: If request_file doesn't exist.
        RuntimeError: If every submission attempt fails.
    """
    last_error: RuntimeError | None = None

    for attempt in range(max_retries):
        try:
            return submit_batch(request_file)
        except RuntimeError as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = backoff_delay(attempt)
                logger.warning(
                    f"Submission attempt {attempt + 1}/{max_retries} failed for "
                    f"{request_file.name}: {e}. Retrying in {delay:.0f}s..."
                )
                time.sleep(delay)

    raise RuntimeError(
        f"Failed to submit {request_file.name} after {max_retries} attempts"
    ) from last_error


def get_batch_status(batch_id: str) -> dict:
    """
    Get the current status of a batch.

    Args:
        batch_id: The Anthropic batch ID (e.g., "msgbatch_...").

    Returns:
        Dict with processing_status, request_counts, ended_at, results_url.

    Raises:
        RuntimeError: If API call fails.
    """
    client = anthropic.Anthropic()

    try:
        batch = client.messages.batches.retrieve(batch_id)
    except anthropic.APIError as e:
        raise RuntimeError(f"Anthropic API error retrieving {batch_id}: {e}") from e

    return {
        "processing_status": batch.processing_status,
        "request_counts": {
            "processing": batch.request_counts.processing,
            "succeeded": batch.request_counts.succeeded,
            "errored": batch.request_counts.errored,
            "canceled": batch.request_counts.canceled,
            "expired": batch.request_counts.expired,
        },
        "ended_at": batch.ended_at.isoformat() if batch.ended_at else None,
        "results_url": batch.results_url,
    }


def download_results(batch_id: str) -> list[dict]:
    """
    Download results for a completed batch.

    Iterates through batch results and extracts relevant fields based on
    result type (succeeded, errored, canceled, expired).

    Args:
        batch_id: The Anthropic batch ID (e.g., "msgbatch_...").

    Returns:
        List of result dicts, each containing:
        - custom_id: str - The custom ID from the original request
        - result_type: str - "succeeded", "errored", "canceled", or "expired"
        - content: str - Model response text (if succeeded)
        - input_tokens: int - Input token count (if succeeded)
        - output_tokens: int - Output token count (if succeeded)
        - model: str - Model that served the request (if succeeded)
        - error: str - Error message (if errored)

    Raises:
        RuntimeError: If API call fails.
    """
    client = anthropic.Anthropic()

    results = []
    try:
        for entry in client.messages.batches.results(batch_id):
            result = {"custom_id": entry.custom_id, "result_type": entry.result.type}

            if entry.result.type == "succeeded":
                message = entry.result.message
                if not message.content:
                    result["result_type"] = "errored"
                    result["error"] = "Empty content array from API"
                else:
                    result["content"] = message.content[0].text
                    result["input_tokens"] = message.usage.input_tokens
                    result["output_tokens"] = message.usage.output_tokens
                    result["model"] = message.model
            elif entry.result.type == "errored":
                error_response = entry.result.error
                result["error"] = f"{error_response.error.type}: {error_response.error.message}"
            elif entry.result.type == "canceled":
                result["error"] = "Request was canceled"
            elif entry.result.type == "expired":
                result["error"] = "Request expired before processing"

            results.append(result)

    except anthropic.APIError as e:
        raise RuntimeError(
            f"Anthropic API error downloading results for {batch_id}: {e}"
        ) from e

    return results
