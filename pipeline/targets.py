"""The sentiment-target verifier: the receipts second pass.

Answers, for a polar comment, "toward whom is this sentiment directed?"
The verdict is a re-derived target (player or None); the attributed
player is not an input. Eval-case contract, prompt, parser, and runner.
"""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import anthropic
import yaml

from pipeline.evaluation import VALID_SOURCES, attribution_match

logger = logging.getLogger(__name__)

# Verifier identity
TARGET_MODEL = "claude-haiku-4-5-20251001"
TARGET_TEMPERATURE = 0.0
TARGET_MAX_TOKENS = 75

# Eval-case contract
POLAR_SENTIMENTS = ("pos", "neg")
TARGET_CATEGORIES = (
    "wrong_player",
    "non_player",
    "subject_not_target",
    "true_toward",  # control: sentiment does land on the attributed player
    "readmit_affirm",  # control: gate-dropped NULL-target row the verifier recovers
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

_SENTIMENT_WORDS = {"pos": "positive", "neg": "negative"}
_JSON_START_RE = re.compile(r"[\[{]")
_JSON_DECODER = json.JSONDecoder()
_NULL_SPELLINGS = {"", "null", "none"}

# Any template edit is a new verifier: bump the version, re-pin the hash test.
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

    # The first JSON object (or array) is the verdict; fences and any
    # explanation the model appends are not part of the contract.
    match = _JSON_START_RE.search(text)
    if match is None:
        return _invalid(text)
    try:
        result, _ = _JSON_DECODER.raw_decode(text, match.start())
    except json.JSONDecodeError:
        return _invalid(text)

    if isinstance(result, list):
        if not result:
            return _invalid(text)
        result = result[0]

    if not isinstance(result, dict) or "t" not in result:
        return _invalid(text)

    target = result["t"]
    confidence = result.get("c")
    parsed: dict = {
        "t": target,
        "c": float(confidence) if confidence is not None else 0.0,
        "valid": True,
    }

    if isinstance(target, list):
        parsed["t_raw"] = target
        parsed["t"] = (
            target[0] if len(target) == 1 and isinstance(target[0], str) else None
        )
    elif isinstance(target, str):
        if target.strip().lower() in _NULL_SPELLINGS:
            parsed["t"] = None
    elif target is not None:
        return _invalid(text)

    return parsed


@dataclass(frozen=True)
class TargetCase:
    """A single ground-truth target-verification case.

    Attributes:
        id: Unique, source-prefixed identifier (e.g. "receipt-m01").
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


def _check_target_consistency(case_label: str, raw: dict) -> None:
    """
    Enforce the category's contract on expected_target.

    Null categories (non_player, subject_not_target) require a null target;
    the controls (true_toward, readmit_affirm) require the attributed
    player; wrong_player requires a different named player.

    Args:
        case_label: The case id, for the error message.
        raw: The raw case dict (category, expected_target, attributed_player).

    Raises:
        ValueError: If the target contradicts the category.
    """
    category, target = raw["category"], raw["expected_target"]
    attributed = raw["attributed_player"]

    if category in ("non_player", "subject_not_target") and target is not None:
        raise ValueError(
            f"Target case {case_label!r} is {category} but names a target {target!r}"
        )
    if category in ("true_toward", "readmit_affirm") and target != attributed:
        raise ValueError(
            f"Target case {case_label!r} is {category} but its target {target!r} "
            f"is not the attributed player {attributed!r}"
        )
    if category == "wrong_player" and (target is None or target == attributed):
        raise ValueError(
            f"Target case {case_label!r} is wrong_player but its target {target!r} "
            f"is not a different player from {attributed!r}"
        )


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

        _check_target_consistency(case_label, raw)

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


def classify_target_cases(
    cases: list[TargetCase],
    prompt_builder: Callable[[str, str], str] = build_target_prompt,
    client: anthropic.Anthropic | None = None,
) -> dict[str, dict]:
    """
    Run each case through the verifier via the synchronous Messages API.

    Uses the verifier's own model parameters and parser, so results
    measure exactly what a batch run would produce for the same prompt.
    Synchronous by design: a ~100-case eval must finish in seconds.

    Args:
        cases: Cases to verify.
        prompt_builder: Builds the user message from (body, sentiment).
            Defaults to the labeled prompt; pass a variant for experiments.
        client: Anthropic client. Defaults to a fresh client reading
            ANTHROPIC_API_KEY from the environment.

    Returns:
        Mapping of case id to parsed verdict (parse_target_response shape).
    """
    if client is None:
        client = anthropic.Anthropic()

    results: dict[str, dict] = {}
    for case in cases:
        response = client.messages.create(
            model=TARGET_MODEL,
            max_tokens=TARGET_MAX_TOKENS,
            temperature=TARGET_TEMPERATURE,
            messages=[
                {"role": "user", "content": prompt_builder(case.text, case.sentiment)}
            ],
        )
        results[case.id] = parse_target_response(response.content[0].text)
        logger.debug("Verified %s: %s", case.id, results[case.id]["t"])

    return results


def verdict_correct(
    result: dict, expected_target: str | None, alias_map: dict[str, str]
) -> bool:
    """
    Judge a verdict the way the pipeline would consume it.

    The named target resolves through the alias map exactly as
    resolve_player() does, so nickname output ("AD") counts when it
    resolves to the expected canonical player and an untracked name
    (a GM, a referee) counts as no target. An invalid parse is never
    correct - not even against an expected null.

    Args:
        result: A parse_target_response dict.
        expected_target: Ground-truth canonical player, or None.
        alias_map: Lowercase alias -> canonical name, as returned by
            build_alias_to_player_map().

    Returns:
        True if the verdict is valid and resolves to the expected target.
    """
    if not result["valid"]:
        return False
    return attribution_match(result["t"], expected_target, alias_map)


def target_accuracy_by_category(
    cases: list[TargetCase], results: dict[str, dict], alias_map: dict[str, str]
) -> dict[str, tuple[int, int]]:
    """
    Tally verdict accuracy per case category.

    Known-miss cases are included in the totals; category floors are set
    with them priced in.

    Args:
        cases: The cases that were verified.
        results: Mapping of case id to verdict (classify_target_cases shape).
        alias_map: Lowercase alias -> canonical name.

    Returns:
        Mapping of category to (correct, total) counts.
    """
    tallies: dict[str, tuple[int, int]] = {}
    for case in cases:
        correct, total = tallies.get(case.category, (0, 0))
        if verdict_correct(results[case.id], case.expected_target, alias_map):
            correct += 1
        tallies[case.category] = (correct, total + 1)

    return tallies
