"""Core batch processing functions for sentiment classification.

Pure functions for prompt building, response parsing, and cost calculation.
API submission functions use the Anthropic Batch API.
"""

import json
import os
import tempfile
from pathlib import Path

import anthropic

# Model configuration
MODEL = "claude-haiku-4-5-20251001"
TEMPERATURE = 0.0
MAX_TOKENS = 50
REQUESTS_PER_BATCH = 100_000

# Batch API pricing (50% discount applied)
INPUT_COST_PER_MTOK = 0.50  # $0.50 per million input tokens
OUTPUT_COST_PER_MTOK = 2.50  # $2.50 per million output tokens

# State file
STATE_FILENAME = "state.json"


def build_prompt(comment_body: str) -> str:
    """
    Build minimal prompt for sentiment classification.

    Args:
        comment_body: The raw Reddit comment text.

    Returns:
        The formatted prompt for the model.
    """
    return f"""Classify sentiment toward NBA players.
Slang: nasty/sick/filthy=positive, washed/brick/fraud/cooked=negative, GOAT=positive.

Comment: {comment_body}

Respond ONLY with JSON: {{"s":"pos|neg|neu","c":0.0-1.0,"p":"Player Name"|null}}"""


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

        # Validate required fields
        if "s" not in result:
            return {"s": "error", "c": 0.0, "p": None, "raw": text}

        # Normalize and validate sentiment value
        sentiment = result.get("s", "")
        if sentiment not in ("pos", "neg", "neu"):
            return {"s": "error", "c": 0.0, "p": None, "raw": text}

        return {
            "s": result["s"],
            "c": float(result.get("c", 0.0)),
            "p": result.get("p"),
        }
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
