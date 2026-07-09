"""Eval harness for the LLM sentiment classifier.

Loads ground-truth cases from a YAML file and runs them through the
production prompt/parse path (pipeline.batch.build_prompt +
parse_response) with production model parameters.

Cases are classified via the synchronous Messages API rather than the
Batch API used in production: identical model, temperature, and token
limits — only the transport differs. This is deliberate; a 23-case eval
must finish in seconds, not hours. Do not "fix" this to use batches.

The prompt_builder parameter on classify_cases exists so prompt-variant
experiments (issue #62 item 3) can reuse this harness against candidate
prompts without touching the pytest suite, which always measures the
production prompt.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import anthropic
import yaml

from pipeline.batch import MAX_TOKENS, MODEL, TEMPERATURE, build_prompt, parse_response
from utils.player_config import resolve_sentiment_player

logger = logging.getLogger(__name__)

VALID_SENTIMENTS = ("pos", "neg", "neu")
VALID_SOURCES = ("synthetic", "mined-v1", "mined-v2")
REQUIRED_KEYS = ("id", "text", "expected", "expected_player", "category", "source")

DEFAULT_CASES_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "eval" / "cases.yaml"
)


@dataclass(frozen=True)
class EvalCase:
    """A single ground-truth classification case.

    Attributes:
        id: Unique, category-prefixed identifier (e.g. "sarcasm-01").
        text: Comment body sent to the classifier.
        expected: Ground-truth sentiment ("pos" | "neg" | "neu").
        expected_player: Ground-truth attributed player, or None.
        category: Grouping used for aggregate accuracy floors.
        source: Provenance ("synthetic" | "mined-v1" | "mined-v2").
        comment_id: Reddit comment id for mined cases, if any.
        note: Free-text context (e.g. why a case is a known miss).
        known_miss: Sentiment test is xfail — the current prompt misses it.
        known_miss_player: Player-attribution test is xfail.
    """

    id: str
    text: str
    expected: str
    expected_player: str | None
    category: str
    source: str
    comment_id: str | None = None
    note: str | None = None
    known_miss: bool = False
    known_miss_player: bool = False


def _read_cases_file(path: Path) -> tuple[dict[str, float], list[dict]]:
    """
    Read and structurally validate the cases YAML file.

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
        raise ValueError(f"Cases file {path} is not a mapping")

    floors = payload.get("meta", {}).get("category_floors")
    if not isinstance(floors, dict):
        raise ValueError(f"Cases file {path} is missing meta.category_floors")

    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"Cases file {path} is missing a 'cases' list")

    return floors, cases


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[EvalCase]:
    """
    Load and validate eval cases from a YAML file.

    Args:
        path: Path to the cases file. Defaults to tests/eval/cases.yaml.

    Returns:
        List of validated EvalCase objects in file order.

    Raises:
        ValueError: On duplicate ids, missing required keys, invalid
            expected/source values, or a case category that has no entry
            in meta.category_floors. Messages name the offending case.
    """
    floors, raw_cases = _read_cases_file(path)

    cases: list[EvalCase] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(raw_cases):
        case_label = raw.get("id", f"case #{index}")

        missing = [key for key in REQUIRED_KEYS if key not in raw]
        if missing:
            raise ValueError(f"Case {case_label!r} is missing keys: {missing}")

        if raw["id"] in seen_ids:
            raise ValueError(f"Duplicate case id: {raw['id']!r}")
        seen_ids.add(raw["id"])

        if raw["expected"] not in VALID_SENTIMENTS:
            raise ValueError(
                f"Case {case_label!r} has invalid expected value "
                f"{raw['expected']!r} (must be one of {VALID_SENTIMENTS})"
            )

        if raw["source"] not in VALID_SOURCES:
            raise ValueError(
                f"Case {case_label!r} has invalid source {raw['source']!r} "
                f"(must be one of {VALID_SOURCES})"
            )

        if raw["category"] not in floors:
            raise ValueError(
                f"Case {case_label!r} has category {raw['category']!r} "
                "with no entry in meta.category_floors"
            )

        cases.append(
            EvalCase(
                id=raw["id"],
                text=raw["text"],
                expected=raw["expected"],
                expected_player=raw["expected_player"],
                category=raw["category"],
                source=raw["source"],
                comment_id=raw.get("comment_id"),
                note=raw.get("note"),
                known_miss=raw.get("known_miss", False),
                known_miss_player=raw.get("known_miss_player", False),
            )
        )

    return cases


def load_category_floors(path: Path = DEFAULT_CASES_PATH) -> dict[str, float]:
    """
    Load and validate per-category accuracy floors.

    Args:
        path: Path to the cases file. Defaults to tests/eval/cases.yaml.

    Returns:
        Mapping of category name to minimum acceptable accuracy in [0, 1].

    Raises:
        ValueError: If a floor is outside [0, 1] or names a category with
            no cases in the file.
    """
    floors, raw_cases = _read_cases_file(path)

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


def classify_cases(
    cases: list[EvalCase],
    prompt_builder: Callable[[str], str] = build_prompt,
    client: anthropic.Anthropic | None = None,
) -> dict[str, dict]:
    """
    Classify each case via the synchronous Messages API.

    Uses production model parameters (MODEL, TEMPERATURE, MAX_TOKENS) and
    the production response parser, so results measure exactly what the
    batch pipeline would produce for the same prompt.

    Args:
        cases: Cases to classify.
        prompt_builder: Builds the user message from a comment body.
            Defaults to the production prompt; pass a variant for prompt
            experiments.
        client: Anthropic client. Defaults to a fresh client reading
            ANTHROPIC_API_KEY from the environment.

    Returns:
        Mapping of case id to parsed result dict (parse_response shape).
    """
    if client is None:
        client = anthropic.Anthropic()

    results: dict[str, dict] = {}
    for case in cases:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            messages=[{"role": "user", "content": prompt_builder(case.text)}],
        )
        results[case.id] = parse_response(response.content[0].text)
        logger.debug("Classified %s: %s", case.id, results[case.id]["s"])

    return results


def normalize_player(name: str | None) -> str | None:
    """
    Normalize a player name for comparison.

    Args:
        name: Raw player name, possibly None.

    Returns:
        Lowercased, stripped name; None for None, empty, or whitespace
        input (an empty string would otherwise substring-match anything).
    """
    if name is None:
        return None
    stripped = name.strip()
    return stripped.lower() if stripped else None


def player_match(predicted: str | None, expected: str | None) -> bool:
    """
    Check whether a predicted player attribution matches the expected one.

    Uses bidirectional substring matching after normalization so partial
    names ("LeBron" vs "LeBron James") count as matches.

    Args:
        predicted: The model's attributed player, or None.
        expected: The ground-truth player, or None.

    Returns:
        True if both are None or either normalized name contains the other.
    """
    pred_norm = normalize_player(predicted)
    exp_norm = normalize_player(expected)

    if pred_norm is None and exp_norm is None:
        return True
    if pred_norm is None or exp_norm is None:
        return False
    return pred_norm in exp_norm or exp_norm in pred_norm


def attribution_match(
    predicted: str | None, expected: str | None, alias_map: dict[str, str]
) -> bool:
    """
    Check attribution the way production consumes the model's p field.

    Resolves the predicted name through the alias map exactly as
    resolve_player() does at aggregation, so nickname or initialism
    output (e.g. "AD") counts as correct when it resolves to the
    expected canonical player. Unresolvable output counts as None —
    matching production, where such attributions are dropped.

    Contrast with player_match(), which compares raw model output by
    substring: useful for measuring what the model literally says
    (issue #62 item 4), but stricter than the pipeline's behavior.

    Args:
        predicted: The model's attributed player, or None.
        expected: The ground-truth canonical player name, or None.
        alias_map: Mapping of lowercase aliases to canonical player names,
            as returned by build_alias_to_player_map().

    Returns:
        True if the resolved prediction equals the expected canonical name.
    """
    return resolve_sentiment_player(predicted, alias_map) == expected


def accuracy_by_category(
    cases: list[EvalCase], results: dict[str, dict]
) -> dict[str, tuple[int, int]]:
    """
    Tally sentiment accuracy per case category.

    Known-miss cases are included in the totals; category floors are set
    with them priced in.

    Args:
        cases: The cases that were classified.
        results: Mapping of case id to parsed result (classify_cases shape).

    Returns:
        Mapping of category to (correct, total) sentiment counts.
    """
    tallies: dict[str, tuple[int, int]] = {}
    for case in cases:
        correct, total = tallies.get(case.category, (0, 0))
        if results[case.id]["s"] == case.expected:
            correct += 1
        tallies[case.category] = (correct, total + 1)

    return tallies
