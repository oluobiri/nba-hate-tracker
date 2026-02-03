"""Core batch processing functions for sentiment classification.

Pure functions for prompt building, response parsing, and cost calculation.
No API calls - designed for use with Anthropic Batch API.
"""

import json

# Model configuration
MODEL = "claude-haiku-4-5-20251001"
TEMPERATURE = 0.0
MAX_TOKENS = 50
REQUESTS_PER_BATCH = 100_000

# Batch API pricing (50% discount applied)
INPUT_COST_PER_MTOK = 0.50  # $0.50 per million input tokens
OUTPUT_COST_PER_MTOK = 2.50  # $2.50 per million output tokens


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
