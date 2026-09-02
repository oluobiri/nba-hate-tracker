"""Unit tests for pipeline/targets.py — all offline, no API calls."""

import hashlib
from pathlib import Path

import pytest
import yaml

from pipeline.targets import (
    TARGET_CATEGORIES,
    TARGET_PROMPT_TEMPLATE,
    TARGET_PROMPT_VERSION,
    build_target_prompt,
    load_target_cases,
    load_target_floors,
    parse_target_response,
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


class TestBuildTargetPrompt:
    def test_renders_body_and_sentiment_word(self):
        """The prompt carries the comment verbatim and the spelled-out label."""
        prompt = build_target_prompt("They traded Luka for Marvin Bagley", "neg")

        assert "Comment: They traded Luka for Marvin Bagley" in prompt
        assert "negative" in prompt
        assert "positive" not in prompt

    def test_positive_label_spelled_out(self):
        """A pos label renders as 'positive'."""
        prompt = build_target_prompt("Really cool from Giannis", "pos")

        assert "positive" in prompt
        assert "negative" not in prompt

    def test_rejects_non_polar_sentiment(self):
        """The verifier is defined over polar rows only."""
        with pytest.raises(ValueError, match="neu"):
            build_target_prompt("some comment", "neu")

    def test_renders_template_exactly(self):
        """Rendering is byte-identical to the frozen template with fields filled."""
        expected = TARGET_PROMPT_TEMPLATE.format(
            sentiment_word="negative", comment_body="test body"
        )

        assert build_target_prompt("test body", "neg") == expected


class TestTargetPromptVersionPin:
    def test_template_hash_matches_labeled_version(self):
        """The template's sha256 matches the pin for TARGET_PROMPT_VERSION.

        Any template edit is a new verifier: it requires a new label, a new
        pinned hash, and a re-baselined target eval suite.
        """
        assert TARGET_PROMPT_VERSION == "v0-draft"
        assert (
            hashlib.sha256(TARGET_PROMPT_TEMPLATE.encode()).hexdigest()
            == "e9f23d42e2f59c63e120dd73caeff36ff154d83a5f6eb12560a0cebdfa9d6aa0"
        )


class TestParseTargetResponse:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ('{"t": "Luka Doncic", "c": 0.9}', {"t": "Luka Doncic", "c": 0.9}),
            ('{"t": null, "c": 0.8}', {"t": None, "c": 0.8}),
            ('```json\n{"t": "AD", "c": 0.7}\n```', {"t": "AD", "c": 0.7}),
            ('{"t": "Nikola Jokic"}', {"t": "Nikola Jokic", "c": 0.0}),
            ('[{"t": "Jokic", "c": 0.6}]', {"t": "Jokic", "c": 0.6}),
        ],
    )
    def test_valid_responses(self, text: str, expected: dict):
        """Well-formed JSON (bare, fenced, or list-wrapped) parses as valid."""
        assert parse_target_response(text) == {**expected, "valid": True}

    def test_single_string_list_target_unwraps(self):
        """A one-element list target is normalized to its string, raw kept."""
        result = parse_target_response('{"t": ["Luka Doncic"], "c": 0.9}')

        assert result["t"] == "Luka Doncic"
        assert result["t_raw"] == ["Luka Doncic"]
        assert result["valid"] is True

    def test_multi_string_list_target_becomes_none(self):
        """A multi-element list target has no single answer and becomes None."""
        result = parse_target_response('{"t": ["Luka", "AD"], "c": 0.9}')

        assert result["t"] is None
        assert result["t_raw"] == ["Luka", "AD"]
        assert result["valid"] is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "not json at all",
            '{"c": 0.9}',
            '{"t": 42, "c": 0.9}',
            "[]",
        ],
    )
    def test_invalid_responses(self, text: str):
        """Malformed output is flagged invalid with a None target, raw kept.

        Invalid must never read as a null verdict: a parse failure is not
        evidence that the sentiment has no target.
        """
        result = parse_target_response(text)

        assert result["valid"] is False
        assert result["t"] is None
        assert result["raw"] == text
