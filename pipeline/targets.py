"""The sentiment-target verifier: the receipts second pass.

Where the sentiment classifier (pipeline/batch.py) labels a comment's tone
and names the player it is about, this verifier answers a narrower
question over polar comments: toward whom is that sentiment directed?
The verdict is a freely re-derived target (player or None) - the
attributed player is deliberately not in the prompt, so a misfiled
receipt is recoverable under its true target.

This module holds the verifier's eval-case contract (tests/eval/
target_cases.yaml). Its prompt, parser, and runner follow in the same
file; both classifiers keep their own {model, prompt} identity.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from pipeline.evaluation import VALID_SOURCES

logger = logging.getLogger(__name__)

POLAR_SENTIMENTS = ("pos", "neg")
_SENTIMENT_WORDS = {"pos": "positive", "neg": "negative"}

# Verifier identity. Starts on the sentiment classifier's model; the target
# eval suite decides whether it stays there.
TARGET_MODEL = "claude-haiku-4-5-20251001"
TARGET_TEMPERATURE = 0.0
TARGET_MAX_TOKENS = 75

# Draft toward-prompt (#91). The attributed player is deliberately absent:
# the verdict is a freely re-derived target so a misfiled receipt is
# recoverable under its true target. Any edit is a new verifier: bump
# TARGET_PROMPT_VERSION and re-pin the hash test.
TARGET_PROMPT_VERSION = "v0-draft"
TARGET_PROMPT_TEMPLATE = """This r/NBA comment was labeled {sentiment_word}. Name the NBA player that {sentiment_word} sentiment is directed at.
The target is the player being praised or criticized - not a player who is merely mentioned, sympathized with, or the subject of someone else's decision.
If the sentiment is directed at a non-player (front office, coach, referees, fans, media) or at no one in particular, answer null.

Comment: {comment_body}

Respond ONLY with JSON: {{"t":"Player Name"|null,"c":0.0-1.0}}"""


def build_target_prompt(comment_body: str, sentiment: str) -> str:
    """
    Build the target-verification prompt for a polar comment.

    Renders TARGET_PROMPT_TEMPLATE, the prompt labeled TARGET_PROMPT_VERSION.

    Args:
        comment_body: The raw Reddit comment text.
        sentiment: The pass-1 polar label ("pos" | "neg").

    Returns:
        The formatted prompt for the model.

    Raises:
        ValueError: If sentiment is not polar.
    """
    if sentiment not in _SENTIMENT_WORDS:
        raise ValueError(
            f"Target prompt is defined for polar sentiment only, got {sentiment!r}"
        )
    return TARGET_PROMPT_TEMPLATE.format(
        sentiment_word=_SENTIMENT_WORDS[sentiment], comment_body=comment_body
    )


def _invalid(text: str) -> dict:
    """The parse-failure result: never a null verdict, always flagged."""
    return {"t": None, "c": 0.0, "valid": False, "raw": text}


def parse_target_response(text: str) -> dict:
    """
    Parse the verifier's response into a structured dict.

    Handles bare JSON, JSON in a markdown fence, a list-wrapped object
    (first element), and malformed output. A parse failure is flagged
    rather than read as a null verdict - "no target" is a valid answer
    the verifier must actually give.

    Args:
        text: Raw text response from the model.

    Returns:
        Success: {"t": str|None, "c": float, "valid": True}. A list-valued
        "t" is normalized (single-string list unwraps, anything else
        becomes None) with the original kept under "t_raw".
        Failure: {"t": None, "c": 0.0, "valid": False, "raw": str}.
    """
    if not text or not text.strip():
        return _invalid(text)

    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        return _invalid(text)

    if isinstance(result, list):
        if not result:
            return _invalid(text)
        result = result[0]

    if not isinstance(result, dict) or "t" not in result:
        return _invalid(text)

    target = result["t"]
    parsed: dict = {"t": target, "c": float(result.get("c", 0.0)), "valid": True}

    if isinstance(target, list):
        parsed["t_raw"] = target
        parsed["t"] = (
            target[0] if len(target) == 1 and isinstance(target[0], str) else None
        )
    elif target is not None and not isinstance(target, str):
        return _invalid(text)

    return parsed


# Three misdirected-sentiment failure families plus two controls: without
# true_toward an always-null verifier scores perfectly; readmit_affirm is
# the gate-dropped NULL-target row the verifier must recover.
TARGET_CATEGORIES = (
    "wrong_player",
    "non_player",
    "sympathetic_subject",
    "true_toward",
    "readmit_affirm",
)

REQUIRED_TARGET_KEYS = (
    "id",
    "text",
    "sentiment",
    "attributed_player",
    "expected_target",
    "category",
    "source",
)

DEFAULT_TARGET_CASES_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "eval" / "target_cases.yaml"
)


@dataclass(frozen=True)
class TargetCase:
    """A single ground-truth target-verification case.

    Attributes:
        id: Unique, category-prefixed identifier (e.g. "sympathetic-01").
        text: Comment body sent to the verifier.
        sentiment: The pass-1 polar label ("pos" | "neg") fed to the prompt.
        attributed_player: Who the pipeline attributed the comment to. Not
            sent to the verifier; it is what the verdict is judged against
            in the control categories.
        expected_target: Ground-truth canonical player the sentiment is
            directed at, or None for a non-player or no target.
        category: One of TARGET_CATEGORIES; groups accuracy floors.
        source: Provenance ("synthetic" | "mined-v1" | "mined-v2").
        comment_id: Reddit comment id for mined cases, if any.
        note: Free-text context (e.g. why a case is a known miss).
        known_miss: Test is xfail - the current prompt misses it.
    """

    id: str
    text: str
    sentiment: str
    attributed_player: str
    expected_target: str | None
    category: str
    source: str
    comment_id: str | None = None
    note: str | None = None
    known_miss: bool = False


def _read_target_cases_file(path: Path) -> tuple[dict[str, float], list[dict]]:
    """
    Read and structurally validate the target-cases YAML file.

    Args:
        path: Path to the cases file.

    Returns:
        Tuple of (category_floors mapping, raw case dicts).

    Raises:
        ValueError: If the top-level structure is malformed.
    """
    with open(path) as f:
        payload = yaml.safe_load(f)

    if not isinstance(payload, dict):
        raise ValueError(f"Target cases file {path} is not a mapping")

    floors = payload.get("meta", {}).get("category_floors")
    if not isinstance(floors, dict):
        raise ValueError(f"Target cases file {path} is missing meta.category_floors")

    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"Target cases file {path} is missing a 'cases' list")

    return floors, cases


def load_target_cases(path: Path = DEFAULT_TARGET_CASES_PATH) -> list[TargetCase]:
    """
    Load and validate target-verification cases from a YAML file.

    Args:
        path: Path to the cases file. Defaults to tests/eval/target_cases.yaml.

    Returns:
        List of validated TargetCase objects in file order.

    Raises:
        ValueError: On duplicate ids, missing required keys (an unlabeled
            queue entry lacks expected_target), a non-polar sentiment, an
            invalid source, a category outside TARGET_CATEGORIES, or a
            category with no entry in meta.category_floors. Messages name
            the offending case.
    """
    floors, raw_cases = _read_target_cases_file(path)

    cases: list[TargetCase] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(raw_cases):
        case_label = raw.get("id", f"case #{index}")

        missing = [key for key in REQUIRED_TARGET_KEYS if key not in raw]
        if missing:
            raise ValueError(f"Target case {case_label!r} is missing keys: {missing}")

        if raw["id"] in seen_ids:
            raise ValueError(f"Duplicate target case id: {raw['id']!r}")
        seen_ids.add(raw["id"])

        if raw["sentiment"] not in POLAR_SENTIMENTS:
            raise ValueError(
                f"Target case {case_label!r} has sentiment {raw['sentiment']!r} "
                f"(must be one of {POLAR_SENTIMENTS})"
            )

        if raw["source"] not in VALID_SOURCES:
            raise ValueError(
                f"Target case {case_label!r} has invalid source {raw['source']!r} "
                f"(must be one of {VALID_SOURCES})"
            )

        if raw["category"] not in TARGET_CATEGORIES:
            raise ValueError(
                f"Target case {case_label!r} has category {raw['category']!r} "
                f"(must be one of {TARGET_CATEGORIES})"
            )

        if raw["category"] not in floors:
            raise ValueError(
                f"Target case {case_label!r} has category {raw['category']!r} "
                "with no entry in meta.category_floors"
            )

        cases.append(
            TargetCase(
                id=raw["id"],
                text=raw["text"],
                sentiment=raw["sentiment"],
                attributed_player=raw["attributed_player"],
                expected_target=raw["expected_target"],
                category=raw["category"],
                source=raw["source"],
                comment_id=raw.get("comment_id"),
                note=raw.get("note"),
                known_miss=raw.get("known_miss", False),
            )
        )

    return cases


def load_target_floors(path: Path = DEFAULT_TARGET_CASES_PATH) -> dict[str, float]:
    """
    Load and validate per-category accuracy floors for the verifier.

    Args:
        path: Path to the cases file. Defaults to tests/eval/target_cases.yaml.

    Returns:
        Mapping of category name to minimum acceptable accuracy in [0, 1].

    Raises:
        ValueError: If a floor is outside [0, 1] or names a category with
            no cases in the file.
    """
    floors, raw_cases = _read_target_cases_file(path)

    for category, floor in floors.items():
        if not isinstance(floor, int | float) or not 0.0 <= floor <= 1.0:
            raise ValueError(
                f"Floor for category {category!r} must be in [0, 1], got {floor!r}"
            )

    case_categories = {raw.get("category") for raw in raw_cases}
    unused = sorted(set(floors) - case_categories)
    if unused:
        raise ValueError(f"Floors defined for categories with no cases: {unused}")

    return {category: float(floor) for category, floor in floors.items()}
