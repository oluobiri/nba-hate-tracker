"""Unit tests for pipeline/targets.py — all offline, no API calls."""

from pathlib import Path

import pytest
import yaml

from pipeline.targets import (
    TARGET_CATEGORIES,
    load_target_cases,
    load_target_floors,
)


def make_target_case(**overrides) -> dict:
    """Build a valid target case dict, with optional field overrides."""
    case = {
        "id": "sympathetic-01",
        "text": "They traded Luka for Marvin Bagley",
        "sentiment": "neg",
        "attributed_player": "Luka Doncic",
        "expected_target": None,
        "category": "sympathetic_subject",
        "source": "mined-v2",
    }
    case.update(overrides)
    return case


def write_target_cases_file(
    tmp_path: Path,
    cases: list[dict],
    floors: dict[str, float] | None = None,
) -> Path:
    """Write a target-cases YAML file into tmp_path and return its path."""
    if floors is None:
        floors = {"sympathetic_subject": 0.0}
    payload = {"meta": {"category_floors": floors}, "cases": cases}
    path = tmp_path / "target_cases.yaml"
    path.write_text(yaml.safe_dump(payload))
    return path


class TestLoadTargetCases:
    def test_loads_valid_file(self, tmp_path):
        """Valid file yields TargetCase objects with fields mapped."""
        path = write_target_cases_file(
            tmp_path,
            [
                make_target_case(),
                make_target_case(
                    id="wrong-01",
                    text="Cole Anthony is bitch made",
                    attributed_player="Stephen Curry",
                    expected_target="Cole Anthony",
                    category="wrong_player",
                ),
            ],
            floors={"sympathetic_subject": 0.0, "wrong_player": 0.0},
        )

        cases = load_target_cases(path)

        assert len(cases) == 2
        assert cases[0].id == "sympathetic-01"
        assert cases[0].sentiment == "neg"
        assert cases[0].attributed_player == "Luka Doncic"
        assert cases[0].expected_target is None
        assert cases[1].expected_target == "Cole Anthony"
        assert cases[1].category == "wrong_player"

    def test_applies_optional_defaults(self, tmp_path):
        """Optional fields default to None/False when omitted."""
        path = write_target_cases_file(tmp_path, [make_target_case()])

        case = load_target_cases(path)[0]

        assert case.comment_id is None
        assert case.note is None
        assert case.known_miss is False

    def test_preserves_optional_fields(self, tmp_path):
        """Optional fields are carried through when present."""
        path = write_target_cases_file(
            tmp_path,
            [
                make_target_case(
                    comment_id="abc123", note="baseline miss", known_miss=True
                )
            ],
        )

        case = load_target_cases(path)[0]

        assert case.comment_id == "abc123"
        assert case.note == "baseline miss"
        assert case.known_miss is True

    def test_rejects_duplicate_ids(self, tmp_path):
        """Duplicate case ids raise ValueError naming the id."""
        path = write_target_cases_file(
            tmp_path, [make_target_case(), make_target_case()]
        )

        with pytest.raises(ValueError, match="sympathetic-01"):
            load_target_cases(path)

    def test_rejects_neutral_sentiment(self, tmp_path):
        """The verifier runs on polar rows only; neu is not a valid input."""
        path = write_target_cases_file(tmp_path, [make_target_case(sentiment="neu")])

        with pytest.raises(ValueError, match="sympathetic-01"):
            load_target_cases(path)

    def test_rejects_invalid_source(self, tmp_path):
        """A source outside the known set raises ValueError."""
        path = write_target_cases_file(
            tmp_path, [make_target_case(source="handwritten")]
        )

        with pytest.raises(ValueError, match="sympathetic-01"):
            load_target_cases(path)

    def test_rejects_missing_required_key(self, tmp_path):
        """A case missing a required key raises ValueError naming the id."""
        case = make_target_case()
        del case["attributed_player"]
        path = write_target_cases_file(tmp_path, [case])

        with pytest.raises(ValueError, match="sympathetic-01"):
            load_target_cases(path)

    def test_rejects_unlabeled_candidate(self, tmp_path):
        """A queue entry pasted without its expected_target key fails loudly."""
        case = make_target_case()
        del case["expected_target"]
        path = write_target_cases_file(tmp_path, [case])

        with pytest.raises(ValueError, match="expected_target"):
            load_target_cases(path)

    def test_rejects_unknown_category(self, tmp_path):
        """A category outside the five verifier categories raises ValueError."""
        path = write_target_cases_file(
            tmp_path,
            [make_target_case(category="sarcasm")],
            floors={"sarcasm": 0.0},
        )

        with pytest.raises(ValueError, match="sarcasm"):
            load_target_cases(path)

    def test_rejects_category_without_floor(self, tmp_path):
        """A case category absent from meta.category_floors raises ValueError."""
        path = write_target_cases_file(
            tmp_path,
            [make_target_case(id="wrong-01", category="wrong_player")],
            floors={"sympathetic_subject": 0.0},
        )

        with pytest.raises(ValueError, match="wrong-01"):
            load_target_cases(path)


class TestLoadTargetFloors:
    def test_loads_floors(self, tmp_path):
        """Floors are returned as a category -> fraction mapping."""
        path = write_target_cases_file(
            tmp_path, [make_target_case()], floors={"sympathetic_subject": 0.8}
        )

        floors = load_target_floors(path)

        assert floors == {"sympathetic_subject": 0.8}

    def test_rejects_floor_out_of_range(self, tmp_path):
        """A floor outside [0, 1] raises ValueError naming the category."""
        path = write_target_cases_file(
            tmp_path, [make_target_case()], floors={"sympathetic_subject": 1.5}
        )

        with pytest.raises(ValueError, match="sympathetic_subject"):
            load_target_floors(path)

    def test_rejects_floor_without_cases(self, tmp_path):
        """A floor category with zero cases raises ValueError."""
        path = write_target_cases_file(
            tmp_path,
            [make_target_case()],
            floors={"sympathetic_subject": 0.0, "wrong_player": 0.5},
        )

        with pytest.raises(ValueError, match="wrong_player"):
            load_target_floors(path)


class TestRealTargetCasesFile:
    def test_cases_file_loads(self):
        """The committed target_cases.yaml parses cleanly."""
        cases = load_target_cases()

        assert all(case.category in TARGET_CATEGORIES for case in cases)

    def test_floors_are_known_categories(self):
        """Every floor names one of the five verifier categories."""
        floors = load_target_floors()

        assert set(floors) <= set(TARGET_CATEGORIES)
