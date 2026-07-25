"""Unit tests for pipeline/evaluation.py — all offline, no API calls."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from pipeline.batch import MAX_TOKENS, MODEL, TEMPERATURE
from pipeline.evaluation import (
    accuracy_by_category,
    attribution_match,
    classify_cases,
    load_cases,
    load_category_floors,
    normalize_player,
    player_match,
)

EXPECTED_CATEGORIES = {
    "clear_positive",
    "clear_negative",
    "neutral",
    "slang_inversion",
    "sarcasm",
    "negative_nickname",
    "short",
    "multi_player",
    "genuine_praise",
}


def make_case(**overrides) -> dict:
    """Build a valid case dict, with optional field overrides."""
    case = {
        "id": "pos-01",
        "text": "LeBron is the GOAT",
        "expected": "pos",
        "expected_player": "LeBron James",
        "category": "clear_positive",
        "source": "synthetic",
    }
    case.update(overrides)
    return case


def write_cases_file(
    tmp_path: Path,
    cases: list[dict],
    floors: dict[str, float] | None = None,
) -> Path:
    """Write a cases YAML file into tmp_path and return its path."""
    if floors is None:
        floors = {"clear_positive": 0.0}
    payload = {"meta": {"category_floors": floors}, "cases": cases}
    path = tmp_path / "cases.yaml"
    path.write_text(yaml.safe_dump(payload))
    return path


class TestLoadCases:
    def test_loads_valid_file(self, tmp_path):
        """Valid file yields EvalCase objects with fields mapped."""
        path = write_cases_file(
            tmp_path,
            [make_case(), make_case(id="pos-02", text="Jokic is a genius")],
        )

        cases = load_cases(path)

        assert len(cases) == 2
        assert cases[0].id == "pos-01"
        assert cases[0].expected == "pos"
        assert cases[0].expected_player == "LeBron James"
        assert cases[1].text == "Jokic is a genius"

    def test_applies_optional_defaults(self, tmp_path):
        """Optional fields default to None/False when omitted."""
        path = write_cases_file(tmp_path, [make_case()])

        case = load_cases(path)[0]

        assert case.comment_id is None
        assert case.note is None
        assert case.known_miss is False
        assert case.known_miss_player is False

    def test_preserves_optional_fields(self, tmp_path):
        """Optional fields are carried through when present."""
        path = write_cases_file(
            tmp_path,
            [
                make_case(
                    source="mined-v1",
                    comment_id="abc123",
                    note="baseline miss",
                    known_miss=True,
                    known_miss_player=True,
                )
            ],
        )

        case = load_cases(path)[0]

        assert case.source == "mined-v1"
        assert case.comment_id == "abc123"
        assert case.note == "baseline miss"
        assert case.known_miss is True
        assert case.known_miss_player is True

    def test_rejects_duplicate_ids(self, tmp_path):
        """Duplicate case ids raise ValueError naming the id."""
        path = write_cases_file(tmp_path, [make_case(), make_case()])

        with pytest.raises(ValueError, match="pos-01"):
            load_cases(path)

    def test_rejects_invalid_sentiment(self, tmp_path):
        """An expected value outside pos|neg|neu raises ValueError."""
        path = write_cases_file(tmp_path, [make_case(expected="positive")])

        with pytest.raises(ValueError, match="pos-01"):
            load_cases(path)

    def test_rejects_invalid_source(self, tmp_path):
        """A source outside the known set raises ValueError."""
        path = write_cases_file(tmp_path, [make_case(source="handwritten")])

        with pytest.raises(ValueError, match="pos-01"):
            load_cases(path)

    def test_rejects_missing_required_key(self, tmp_path):
        """A case missing a required key raises ValueError naming the id."""
        case = make_case()
        del case["category"]
        path = write_cases_file(tmp_path, [case])

        with pytest.raises(ValueError, match="pos-01"):
            load_cases(path)

    def test_rejects_category_without_floor(self, tmp_path):
        """A case category absent from meta.category_floors raises ValueError."""
        path = write_cases_file(
            tmp_path,
            [make_case(id="sarcasm-01", category="sarcasm")],
            floors={"clear_positive": 0.0},
        )

        with pytest.raises(ValueError, match="sarcasm-01"):
            load_cases(path)


class TestLoadCategoryFloors:
    def test_loads_floors(self, tmp_path):
        """Floors are returned as a category → fraction mapping."""
        path = write_cases_file(tmp_path, [make_case()], floors={"clear_positive": 0.8})

        floors = load_category_floors(path)

        assert floors == {"clear_positive": 0.8}

    def test_rejects_floor_out_of_range(self, tmp_path):
        """A floor outside [0, 1] raises ValueError naming the category."""
        path = write_cases_file(tmp_path, [make_case()], floors={"clear_positive": 1.5})

        with pytest.raises(ValueError, match="clear_positive"):
            load_category_floors(path)

    def test_rejects_floor_without_cases(self, tmp_path):
        """A floor category with zero cases raises ValueError."""
        path = write_cases_file(
            tmp_path,
            [make_case()],
            floors={"clear_positive": 0.0, "sarcasm": 0.5},
        )

        with pytest.raises(ValueError, match="sarcasm"):
            load_category_floors(path)


class TestNormalizePlayer:
    @pytest.mark.parametrize(
        "name,expected",
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("LeBron James", "lebron james"),
            ("  LeBron James  ", "lebron james"),
        ],
    )
    def test_normalizes(self, name: str | None, expected: str | None):
        """Names lowercase and strip; None/empty/whitespace collapse to None."""
        assert normalize_player(name) == expected


class TestPlayerMatch:
    @pytest.mark.parametrize(
        "predicted,expected,matches",
        [
            (None, None, True),
            ("LeBron James", None, False),
            (None, "LeBron James", False),
            ("LeBron James", "LeBron James", True),
            ("LeBron", "LeBron James", True),
            ("lebron james", "LeBron", True),
            ("Stephen Curry", "LeBron James", False),
            ("", None, True),
        ],
    )
    def test_matches(self, predicted: str | None, expected: str | None, matches: bool):
        """Bidirectional substring match after normalization."""
        assert player_match(predicted, expected) is matches


class TestAttributionMatch:
    ALIAS_MAP = {
        "ad": "Anthony Davis",
        "anthony davis": "Anthony Davis",
        "lebron": "LeBron James",
        "lebron james": "LeBron James",
    }

    @pytest.mark.parametrize(
        "predicted,expected,matches",
        [
            ("AD", "Anthony Davis", True),
            ("Anthony Davis", "Anthony Davis", True),
            ("LeBron", "Anthony Davis", False),
            (None, None, True),
            (None, "Anthony Davis", False),
            ("AD", None, False),
            ("the refs", None, True),
            ("the refs", "Anthony Davis", False),
        ],
    )
    def test_matches(self, predicted: str | None, expected: str | None, matches: bool):
        """Predicted resolves through the alias map as production does."""
        assert attribution_match(predicted, expected, self.ALIAS_MAP) is matches


class TestClassifyCases:
    def make_client(self, response_text: str) -> Mock:
        """Build a mock Anthropic client returning fixed response text."""
        client = Mock()
        client.messages.create.return_value = Mock(content=[Mock(text=response_text)])
        return client

    def load_two_cases(self, tmp_path) -> list:
        """Two valid cases for keyed-results assertions."""
        path = write_cases_file(
            tmp_path,
            [make_case(), make_case(id="pos-02", text="Jokic is a genius")],
        )
        return load_cases(path)

    def test_returns_results_keyed_by_case_id(self, tmp_path):
        """Each case id maps to its parsed classification."""
        cases = self.load_two_cases(tmp_path)
        client = self.make_client('{"s": "pos", "c": 0.9, "p": "LeBron James"}')

        results = classify_cases(cases, client=client)

        assert set(results) == {"pos-01", "pos-02"}
        assert results["pos-01"] == {"s": "pos", "c": 0.9, "p": "LeBron James"}

    def test_uses_production_model_params(self, tmp_path):
        """Requests go out with production MODEL/TEMPERATURE/MAX_TOKENS."""
        cases = self.load_two_cases(tmp_path)[:1]
        client = self.make_client('{"s": "pos", "c": 0.9, "p": null}')

        classify_cases(cases, client=client)

        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["model"] == MODEL
        assert kwargs["temperature"] == TEMPERATURE
        assert kwargs["max_tokens"] == MAX_TOKENS

    def test_uses_prompt_builder(self, tmp_path):
        """The prompt_builder callable shapes the user message."""
        cases = self.load_two_cases(tmp_path)[:1]
        client = self.make_client('{"s": "pos", "c": 0.9, "p": null}')

        classify_cases(
            cases, prompt_builder=lambda body: f"VARIANT: {body}", client=client
        )

        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["messages"] == [
            {"role": "user", "content": "VARIANT: LeBron is the GOAT"}
        ]

    def test_malformed_response_yields_error_dict(self, tmp_path):
        """Unparseable model output surfaces as the parse_response error dict."""
        cases = self.load_two_cases(tmp_path)[:1]
        client = self.make_client("not json at all")

        results = classify_cases(cases, client=client)

        assert results["pos-01"]["s"] == "error"


class TestAccuracyByCategory:
    def test_counts_correct_per_category(self, tmp_path):
        """Correct/total tallies are grouped by case category."""
        path = write_cases_file(
            tmp_path,
            [
                make_case(),
                make_case(id="pos-02", text="Jokic is a genius"),
                make_case(
                    id="sarcasm-01",
                    text="Wow Simmons shot a three",
                    expected="neg",
                    category="sarcasm",
                ),
            ],
            floors={"clear_positive": 0.0, "sarcasm": 0.0},
        )
        cases = load_cases(path)
        results = {
            "pos-01": {"s": "pos", "c": 0.9, "p": None},
            "pos-02": {"s": "neg", "c": 0.8, "p": None},
            "sarcasm-01": {"s": "neg", "c": 0.7, "p": None},
        }

        accuracy = accuracy_by_category(cases, results)

        assert accuracy == {"clear_positive": (1, 2), "sarcasm": (1, 1)}

    def test_error_results_count_incorrect(self, tmp_path):
        """Parse-error results count against accuracy, not as skips."""
        path = write_cases_file(tmp_path, [make_case()])
        cases = load_cases(path)
        results = {"pos-01": {"s": "error", "c": 0.0, "p": None, "raw": "?"}}

        accuracy = accuracy_by_category(cases, results)

        assert accuracy == {"clear_positive": (0, 1)}

    def test_includes_known_miss_cases(self, tmp_path):
        """known_miss cases stay in the totals — floors price them in."""
        path = write_cases_file(tmp_path, [make_case(known_miss=True)])
        cases = load_cases(path)
        results = {"pos-01": {"s": "neg", "c": 0.9, "p": None}}

        accuracy = accuracy_by_category(cases, results)

        assert accuracy == {"clear_positive": (0, 1)}


class TestRealCasesFile:
    def test_cases_file_loads_with_99_cases(self):
        """The committed cases.yaml parses cleanly at its expanded size."""
        cases = load_cases()

        assert len(cases) == 99

    def test_floors_cover_expected_categories(self):
        """Floors exist for exactly the nine post-expansion categories."""
        floors = load_category_floors()

        assert set(floors) == EXPECTED_CATEGORIES
