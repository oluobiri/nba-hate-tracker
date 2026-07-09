"""Live accuracy eval of the production sentiment classifier.

Deselected by default (see addopts in pyproject.toml). Run with:

    uv run pytest -m eval --maxfail=0 -rxX -v

--maxfail=0 overrides the -x in addopts so one miss doesn't hide the
rest of the accuracy picture; -rxX reports xfails and xpasses (a prompt
improvement shows up as XPASS on a known_miss case).

Do NOT run with pytest-xdist (-n): the session-scoped eval_results
fixture runs once per worker, multiplying API spend for zero benefit.
"""

import pytest

from pipeline.evaluation import (
    EvalCase,
    accuracy_by_category,
    attribution_match,
    load_cases,
    load_category_floors,
)
from utils.player_config import build_alias_to_player_map

pytestmark = pytest.mark.eval

CASES = load_cases()
FLOORS = load_category_floors()
ALIAS_MAP = build_alias_to_player_map()


def _case_params(known_miss_attr: str) -> list:
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
            if getattr(case, known_miss_attr)
            else [],
        )
        for case in CASES
    ]


class TestSentimentPerCase:
    @pytest.mark.parametrize("case", _case_params("known_miss"))
    def test_sentiment(self, case: EvalCase, eval_results: dict[str, dict]):
        """The production prompt classifies this case's sentiment correctly."""
        result = eval_results[case.id]
        assert result["s"] == case.expected, (
            f"{case.id}: expected {case.expected!r}, got {result['s']!r} "
            f"(confidence {result['c']}) for text {case.text!r}"
            + (f" — note: {case.note}" if case.note else "")
        )


class TestPlayerAttributionPerCase:
    @pytest.mark.parametrize("case", _case_params("known_miss_player"))
    def test_player(self, case: EvalCase, eval_results: dict[str, dict]):
        """The model's p field, resolved as production does, matches."""
        result = eval_results[case.id]
        assert attribution_match(result["p"], case.expected_player, ALIAS_MAP), (
            f"{case.id}: expected player {case.expected_player!r}, "
            f"got {result['p']!r} (unresolved or wrong after alias-map "
            f"resolution) for text {case.text!r}"
        )


class TestCategoryFloors:
    @pytest.mark.parametrize("category,floor", sorted(FLOORS.items()))
    def test_category_accuracy_floor(
        self, category: str, floor: float, eval_results: dict[str, dict]
    ):
        """Sentiment accuracy for the category stays at or above its floor."""
        correct, total = accuracy_by_category(CASES, eval_results)[category]
        accuracy = correct / total
        assert accuracy >= floor, (
            f"{category}: accuracy {correct}/{total} ({accuracy:.2f}) "
            f"below floor {floor:.2f}"
        )
