"""The sentiment classifier: the pipeline's first classification pass.

Labels each comment pos/neg/neu with a confidence and the player the
sentiment is about. Identity (model, sampling, frozen prompt), the
response parser, and the stage instance the transport and the eval
harness run it as.
"""

import json

from pipeline.stage import ClassifierStage

# Model configuration
MODEL = "claude-haiku-4-5-20251001"
TEMPERATURE = 0.0
MAX_TOKENS = 75

# Batch API pricing (50% discount applied)
INPUT_COST_PER_MTOK = 0.50  # $0.50 per million input tokens
OUTPUT_COST_PER_MTOK = 2.50  # $2.50 per million output tokens
AVG_INPUT_TOKENS = 60  # measured mean per request (notebook cost analysis)


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
        A non-numeric "c" reads 0.0; the label is never invalidated by it.
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

        # A non-numeric c must not cost the label: degrade to 0.0, keep s/p
        try:
            confidence = float(result.get("c", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        parsed = {"s": result["s"], "c": confidence, "p": result.get("p")}

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


SENTIMENT_STAGE = ClassifierStage(
    name="sentiment",
    model=MODEL,
    max_tokens=MAX_TOKENS,
    sampling_params={"temperature": TEMPERATURE},
    prompt_version=PROMPT_VERSION,
    prompt_template=PROMPT_TEMPLATE,
    build_prompt=build_prompt,
    parse_response=parse_response,
    input_cost_per_mtok=INPUT_COST_PER_MTOK,
    output_cost_per_mtok=OUTPUT_COST_PER_MTOK,
    avg_input_tokens=AVG_INPUT_TOKENS,
)
