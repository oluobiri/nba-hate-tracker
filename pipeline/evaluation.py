"""Eval harness for the LLM classifier stages.

Loads ground-truth cases from a YAML file and runs them through a
stage's production prompt/parse path with the stage's model parameters.
The loader, floors, runner, and tally are generic over a ClassifierStage;
each stage supplies its case type, the per-case checks its contract
needs, the prompt arguments a case yields, and what "correct" means.
The sentiment classifier's case type and wrappers live here; the target
verifier's live in pipeline.targets.

Cases are classified via the synchronous Messages API rather than the
Batch API used in production: identical model, sampling, and token
limits — only the transport differs. This is deliberate; a ~100-case
eval must finish in seconds, not hours. Do not "fix" this to use batches.

The prompt_builder parameter on the runners exists so prompt-variant
experiments can reuse this harness against candidate prompts without
touching the pytest suites, which always measure the frozen prompt.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
import yaml

from pipeline.sentiment import SENTIMENT_STAGE, build_prompt
from pipeline.stage import ClassifierStage
from utils.player_config import resolve_sentiment_player

logger = logging.getLogger(__name__)

VALID_SENTIMENTS = ("pos", "neg", "neu")
VALID_SOURCES = ("synthetic", "mined-v1", "mined-v2")
REQUIRED_KEYS = ("id", "text", "expected", "expected_player", "category", "source")

DEFAULT_CASES_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "eval" / "cases.yaml"
)


# ---------------------------------------------------------------------------
# Generic harness: any stage
# ---------------------------------------------------------------------------


def read_cases_file(
    path: Path, label: str = "Cases"
) -> tuple[dict[str, float], list[dict]]:
    """
    Read and structurally validate a cases YAML file.

    Args:
        path: Path to the cases file.
        label: Noun for error messages (e.g. "Cases", "Target cases").

    Returns:
        Tuple of (category_floors mapping, raw case dicts).

    Raises:
        ValueError: If the top-level structure is malformed.
    """
    with open(path) as f:
        payload = yaml.safe_load(f)

    if not isinstance(payload, dict):
        raise ValueError(f"{label} file {path} is not a mapping")

    floors = payload.get("meta", {}).get("category_floors")
    if not isinstance(floors, dict):
        raise ValueError(f"{label} file {path} is missing meta.category_floors")

    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"{label} file {path} is missing a 'cases' list")

    return floors, cases


def load_case_file(
    path: Path,
    *,
    required_keys: tuple[str, ...],
    factory: Callable[[dict], Any],
    check: Callable[[str, dict], None] | None = None,
    label: str = "Cases",
) -> list:
    """
    Load and validate cases from a YAML file into a stage's case type.

    Shared checks: required keys, duplicate ids, a valid source, and a
    category with an entry in meta.category_floors. A stage's own
    contract (valid labels, category consistency) runs via `check`.

    Args:
        path: Path to the cases file.
        required_keys: Keys every raw case must carry.
        factory: Builds the stage's case object from a validated raw dict.
        check: Stage-specific validation of (case_label, raw); raises
            ValueError naming the case. Runs after the shared key/id/source
            checks and before the floors check.
        label: Noun for error messages.

    Returns:
        List of case objects in file order.

    Raises:
        ValueError: On any failed check; messages name the offending case.
    """
    floors, raw_cases = read_cases_file(path, label)
    noun = label[:-1] if label.endswith("s") else label

    cases: list = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(raw_cases):
        case_label = raw.get("id", f"case #{index}")

        missing = [key for key in required_keys if key not in raw]
        if missing:
            raise ValueError(f"{noun} {case_label!r} is missing keys: {missing}")

        if raw["id"] in seen_ids:
            raise ValueError(f"Duplicate {noun.lower()} id: {raw['id']!r}")
        seen_ids.add(raw["id"])

        if raw["source"] not in VALID_SOURCES:
            raise ValueError(
                f"{noun} {case_label!r} has invalid source {raw['source']!r} "
                f"(must be one of {VALID_SOURCES})"
            )

        if check is not None:
            check(case_label, raw)

        if raw["category"] not in floors:
            raise ValueError(
                f"{noun} {case_label!r} has category {raw['category']!r} "
                "with no entry in meta.category_floors"
            )

        cases.append(factory(raw))

    return cases


def load_floors(path: Path, label: str = "Cases") -> dict[str, float]:
    """
    Load and validate per-category accuracy floors from a cases file.

    Args:
        path: Path to the cases file.
        label: Noun for error messages.

    Returns:
        Mapping of category name to minimum acceptable accuracy in [0, 1].

    Raises:
        ValueError: If a floor is outside [0, 1] or names a category with
            no cases in the file.
    """
    floors, raw_cases = read_cases_file(path, label)

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


def run_cases(
    stage: ClassifierStage,
    cases: list,
    case_prompt_args: Callable[[Any], tuple],
    prompt_builder: Callable[..., str] | None = None,
    client: anthropic.Anthropic | None = None,
) -> dict[str, dict]:
    """
    Run each case through a stage via the synchronous Messages API.

    Uses the stage's model, sampling params, max_tokens, and parser, so
    results measure exactly what a batch run would produce for the same
    prompt.

    Args:
        stage: The classifier stage to run.
        cases: Case objects with an `id` attribute.
        case_prompt_args: Yields the positional arguments the prompt
            builder takes for a case (e.g. (text,) or (text, sentiment)).
        prompt_builder: Builds the user message. Defaults to the stage's
            frozen prompt; pass a variant for experiments.
        client: Anthropic client. Defaults to a fresh client reading
            ANTHROPIC_API_KEY from the environment.

    Returns:
        Mapping of case id to the stage's parsed result plus "raw" (the
        full response text) and "stop_reason", so output format and
        truncation can be measured alongside accuracy.
    """
    if client is None:
        client = anthropic.Anthropic()
    if prompt_builder is None:
        prompt_builder = stage.build_prompt

    results: dict[str, dict] = {}
    for case in cases:
        response = client.messages.create(
            model=stage.model,
            max_tokens=stage.max_tokens,
            **stage.sampling_params,
            messages=[
                {"role": "user", "content": prompt_builder(*case_prompt_args(case))}
            ],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        results[case.id] = {
            **stage.parse_response(text),
            "raw": text,
            "stop_reason": response.stop_reason,
        }
        logger.debug("%s %s: %s", stage.name, case.id, results[case.id])

    return results


def tally_by_category(
    cases: list, results: dict[str, dict], correct: Callable[[Any, dict], bool]
) -> dict[str, tuple[int, int]]:
    """
    Tally per-category accuracy under a stage's notion of correct.

    Known-miss cases are included in the totals; category floors are set
    with them priced in.

    Args:
        cases: Case objects with `id` and `category` attributes.
        results: Mapping of case id to result (run_cases shape).
        correct: Judges (case, result) -> whether the result is right.

    Returns:
        Mapping of category to (correct, total) counts.
    """
    tallies: dict[str, tuple[int, int]] = {}
    for case in cases:
        hits, total = tallies.get(case.category, (0, 0))
        if correct(case, results[case.id]):
            hits += 1
        tallies[case.category] = (hits, total + 1)

    return tallies


# ---------------------------------------------------------------------------
# The sentiment classifier's case type and wrappers
# ---------------------------------------------------------------------------


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


def _check_sentiment_case(case_label: str, raw: dict) -> None:
    """Enforce the sentiment case contract: a valid expected label."""
    if raw["expected"] not in VALID_SENTIMENTS:
        raise ValueError(
            f"Case {case_label!r} has invalid expected value "
            f"{raw['expected']!r} (must be one of {VALID_SENTIMENTS})"
        )


def _sentiment_case(raw: dict) -> EvalCase:
    """Build an EvalCase from a validated raw dict."""
    return EvalCase(
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


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[EvalCase]:
    """
    Load and validate sentiment eval cases from a YAML file.

    Args:
        path: Path to the cases file. Defaults to tests/eval/cases.yaml.

    Returns:
        List of validated EvalCase objects in file order.

    Raises:
        ValueError: On duplicate ids, missing required keys, invalid
            expected/source values, or a case category that has no entry
            in meta.category_floors. Messages name the offending case.
    """
    return load_case_file(
        path,
        required_keys=REQUIRED_KEYS,
        factory=_sentiment_case,
        check=_check_sentiment_case,
    )


def load_category_floors(path: Path = DEFAULT_CASES_PATH) -> dict[str, float]:
    """
    Load and validate the sentiment suite's per-category accuracy floors.

    Args:
        path: Path to the cases file. Defaults to tests/eval/cases.yaml.

    Returns:
        Mapping of category name to minimum acceptable accuracy in [0, 1].

    Raises:
        ValueError: If a floor is outside [0, 1] or names a category with
            no cases in the file.
    """
    return load_floors(path)


def classify_cases(
    cases: list[EvalCase],
    prompt_builder: Callable[[str], str] = build_prompt,
    client: anthropic.Anthropic | None = None,
) -> dict[str, dict]:
    """
    Classify each sentiment case via the synchronous Messages API.

    Args:
        cases: Cases to classify.
        prompt_builder: Builds the user message from a comment body.
            Defaults to the production prompt; pass a variant for prompt
            experiments.
        client: Anthropic client. Defaults to a fresh client reading
            ANTHROPIC_API_KEY from the environment.

    Returns:
        Mapping of case id to parsed result (parse_response shape plus
        "raw" and "stop_reason").
    """
    return run_cases(
        SENTIMENT_STAGE,
        cases,
        lambda case: (case.text,),
        prompt_builder=prompt_builder,
        client=client,
    )


def accuracy_by_category(
    cases: list[EvalCase], results: dict[str, dict]
) -> dict[str, tuple[int, int]]:
    """
    Tally sentiment accuracy per case category.

    Args:
        cases: The cases that were classified.
        results: Mapping of case id to parsed result (classify_cases shape).

    Returns:
        Mapping of category to (correct, total) sentiment counts.
    """
    return tally_by_category(
        cases, results, lambda case, result: result["s"] == case.expected
    )


# ---------------------------------------------------------------------------
# Attribution comparison helpers
# ---------------------------------------------------------------------------


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
