"""Live accuracy eval of the sentiment-target verifier (the receipts pass).

Deselected by default (see addopts in pyproject.toml). Run with:

    uv run pytest -m eval tests/eval/test_target_eval.py --maxfail=0 -rxX -v

Same conventions as the sentiment suite: --maxfail=0 so one miss doesn't
hide the accuracy picture, -rxX so a prompt improvement shows up as XPASS
on a known_miss case, and never pytest-xdist (the session-scoped fixture
would run once per worker).
"""

import pytest

from pipeline.targets import (
    TargetCase,
    load_target_cases,
    load_target_floors,
    target_accuracy_by_category,
    verdict_correct,
)
from utils.player_config import build_alias_to_player_map

pytestmark = pytest.mark.eval

CASES = load_target_cases()
FLOORS = load_target_floors()
ALIAS_MAP = build_alias_to_player_map()


def _case_params() -> list:
    """Build per-case params, applying xfail marks from known-miss flags."""
    return [
        pytest.param(
            case,
            id=case.id,
            marks=[
                pytest.mark.xfail(
                    strict=False, reason=case.note or "known miss at baseline"
                )
            ]
            if case.known_miss
            else [],
        )
        for case in CASES
    ]


class TestTargetPerCase:
    @pytest.mark.parametrize("case", _case_params())
    def test_target(self, case: TargetCase, target_results: dict[str, dict]):
        """The verifier names this case's true target, resolved as production does."""
        result = target_results[case.id]
        assert verdict_correct(result, case.expected_target, ALIAS_MAP), (
            f"{case.id}: expected target {case.expected_target!r}, got "
            f"{result['t']!r} (valid={result['valid']}, confidence {result['c']}) "
            f"for {case.sentiment} text {case.text!r} attributed to "
            f"{case.attributed_player!r}"
            + (f" - note: {case.note}" if case.note else "")
        )


class TestTargetCategoryFloors:
    @pytest.mark.parametrize("category,floor", sorted(FLOORS.items()))
    def test_category_accuracy_floor(
        self, category: str, floor: float, target_results: dict[str, dict]
    ):
        """Verdict accuracy for the category stays at or above its floor."""
        correct, total = target_accuracy_by_category(CASES, target_results, ALIAS_MAP)[
            category
        ]
        accuracy = correct / total
        assert accuracy >= floor, (
            f"{category}: accuracy {correct}/{total} ({accuracy:.2f}) "
            f"below floor {floor:.2f}"
        )
