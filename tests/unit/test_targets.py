"""Unit tests for pipeline/targets.py — all offline, no API calls."""

import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from pipeline.targets import (
    TARGET_CATEGORIES,
    TARGET_MAX_TOKENS,
    TARGET_MODEL,
    TARGET_PROMPT_TEMPLATE,
    TARGET_PROMPT_VERSION,
    TARGET_TEMPERATURE,
    build_target_prompt,
    classify_target_cases,
    load_target_cases,
    load_target_floors,
    parse_target_response,
    target_accuracy_by_category,
    verdict_correct,
)

ALIAS_MAP = {
    "ad": "Anthony Davis",
    "anthony davis": "Anthony Davis",
    "luka": "Luka Doncic",
    "luka doncic": "Luka Doncic",
}


def make_target_case(**overrides) -> dict:
    """Build a valid target case dict, with optional field overrides."""
    case = {
        "id": "subject-01",
        "text": "They traded Luka for Marvin Bagley",
        "sentiment": "neg",
        "attributed_player": "Luka Doncic",
        "expected_target": None,
        "category": "subject_not_target",
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
        floors = {"subject_not_target": 0.0}
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
            floors={"subject_not_target": 0.0, "wrong_player": 0.0},
        )

        cases = load_target_cases(path)

        assert len(cases) == 2
        assert cases[0].id == "subject-01"
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

        with pytest.raises(ValueError, match="subject-01"):
            load_target_cases(path)

    def test_rejects_neutral_sentiment(self, tmp_path):
        """The verifier runs on polar rows only; neu is not a valid input."""
        path = write_target_cases_file(tmp_path, [make_target_case(sentiment="neu")])

        with pytest.raises(ValueError, match="subject-01"):
            load_target_cases(path)

    def test_rejects_invalid_source(self, tmp_path):
        """A source outside the known set raises ValueError."""
        path = write_target_cases_file(
            tmp_path, [make_target_case(source="handwritten")]
        )

        with pytest.raises(ValueError, match="subject-01"):
            load_target_cases(path)

    def test_rejects_missing_required_key(self, tmp_path):
        """A case missing a required key raises ValueError naming the id."""
        case = make_target_case()
        del case["attributed_player"]
        path = write_target_cases_file(tmp_path, [case])

        with pytest.raises(ValueError, match="subject-01"):
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
            floors={"subject_not_target": 0.0},
        )

        with pytest.raises(ValueError, match="wrong-01"):
            load_target_cases(path)


class TestLoadTargetCasesConsistency:
    """Each category pins expected_target's relationship to attributed_player."""

    def test_null_category_rejects_named_target(self, tmp_path):
        """A subject_not_target / non_player case must have a null target."""
        path = write_target_cases_file(
            tmp_path, [make_target_case(expected_target="Luka Doncic")]
        )

        with pytest.raises(ValueError, match="subject-01"):
            load_target_cases(path)

    def test_control_category_rejects_other_target(self, tmp_path):
        """A true_toward / readmit_affirm case must target the attributed player."""
        path = write_target_cases_file(
            tmp_path,
            [
                make_target_case(
                    id="true-01",
                    category="true_toward",
                    expected_target="Anthony Davis",
                )
            ],
            floors={"true_toward": 0.0},
        )

        with pytest.raises(ValueError, match="true-01"):
            load_target_cases(path)

    def test_control_category_rejects_null_target(self, tmp_path):
        """A readmit_affirm case with a null target is a labeling slip."""
        path = write_target_cases_file(
            tmp_path,
            [make_target_case(id="readmit-01", category="readmit_affirm")],
            floors={"readmit_affirm": 0.0},
        )

        with pytest.raises(ValueError, match="readmit-01"):
            load_target_cases(path)

    @pytest.mark.parametrize("expected_target", [None, "Luka Doncic"])
    def test_wrong_player_requires_a_different_player(
        self, tmp_path, expected_target: str | None
    ):
        """A wrong_player case names a tracked player other than the attributed one."""
        path = write_target_cases_file(
            tmp_path,
            [
                make_target_case(
                    id="wrong-01",
                    category="wrong_player",
                    expected_target=expected_target,
                )
            ],
            floors={"wrong_player": 0.0},
        )

        with pytest.raises(ValueError, match="wrong-01"):
            load_target_cases(path)

    def test_accepts_consistent_cases(self, tmp_path):
        """One consistent case per category loads cleanly."""
        path = write_target_cases_file(
            tmp_path,
            [
                make_target_case(),
                make_target_case(id="non-01", category="non_player"),
                make_target_case(
                    id="wrong-01",
                    category="wrong_player",
                    expected_target="Anthony Davis",
                ),
                make_target_case(
                    id="true-01", category="true_toward", expected_target="Luka Doncic"
                ),
                make_target_case(
                    id="readmit-01",
                    category="readmit_affirm",
                    expected_target="Luka Doncic",
                ),
            ],
            floors={c: 0.0 for c in TARGET_CATEGORIES},
        )

        assert len(load_target_cases(path)) == 5


class TestLoadTargetFloors:
    def test_loads_floors(self, tmp_path):
        """Floors are returned as a category -> fraction mapping."""
        path = write_target_cases_file(
            tmp_path, [make_target_case()], floors={"subject_not_target": 0.8}
        )

        floors = load_target_floors(path)

        assert floors == {"subject_not_target": 0.8}

    def test_rejects_floor_out_of_range(self, tmp_path):
        """A floor outside [0, 1] raises ValueError naming the category."""
        path = write_target_cases_file(
            tmp_path, [make_target_case()], floors={"subject_not_target": 1.5}
        )

        with pytest.raises(ValueError, match="subject_not_target"):
            load_target_floors(path)

    def test_rejects_floor_without_cases(self, tmp_path):
        """A floor category with zero cases raises ValueError."""
        path = write_target_cases_file(
            tmp_path,
            [make_target_case()],
            floors={"subject_not_target": 0.0, "wrong_player": 0.5},
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

    @pytest.mark.parametrize(
        "text,expected",
        [
            (
                '```json\n{"t": null, "c": 0.8}\n```\n\nThe sentiment is directed at the GM.',
                {"t": None, "c": 0.8},
            ),
            (
                '{"t":"Nico Harrison","c":0.9}\n\nWait, let me reconsider. ```json\n{"t":null,"c":0.',
                {"t": "Nico Harrison", "c": 0.9},
            ),
            ('```json\n{"t":"null","c":0.8}\n```', {"t": None, "c": 0.8}),
            ('{"t": "None", "c": 0.8}', {"t": None, "c": 0.8}),
            ('{"t": "", "c": 0.8}', {"t": None, "c": 0.8}),
            ('{"t": "Luka Doncic", "c": null}', {"t": "Luka Doncic", "c": 0.0}),
        ],
    )
    def test_extracts_first_object_and_normalizes_null_spellings(
        self, text: str, expected: dict
    ):
        """Prose after the JSON, a spelled-out null, or a null confidence still parse.

        The model's explanation is not part of the contract; the first JSON
        object is the verdict. A null spelled as a string is a null verdict.
        """
        assert parse_target_response(text) == {**expected, "valid": True}

    @pytest.mark.parametrize("raw_c", ['"high"', "[0.9]", '{"x": 1}', '"0.9abc"'])
    def test_non_numeric_confidence_degrades_to_zero(self, raw_c: str):
        """A non-numeric confidence never raises; the verdict stays valid at c=0.0."""
        result = parse_target_response(f'{{"t": "LeBron James", "c": {raw_c}}}')

        assert result == {"t": "LeBron James", "c": 0.0, "valid": True}

    def test_prose_without_json_is_invalid(self):
        """Explanation with no JSON object anywhere is a parse failure."""
        result = parse_target_response(
            "The sentiment is directed at the GM, not a player."
        )

        assert result["valid"] is False

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


class TestClassifyTargetCases:
    def make_client(self, response_text: str) -> Mock:
        """Build a mock Anthropic client returning fixed response text."""
        client = Mock()
        client.messages.create.return_value = Mock(content=[Mock(text=response_text)])
        return client

    def load_two_cases(self, tmp_path) -> list:
        """Two valid cases for keyed-results assertions."""
        path = write_target_cases_file(
            tmp_path,
            [
                make_target_case(),
                make_target_case(
                    id="true-01",
                    text="AD showed up to collect a check and dip",
                    attributed_player="Anthony Davis",
                    expected_target="Anthony Davis",
                    category="true_toward",
                ),
            ],
            floors={"subject_not_target": 0.0, "true_toward": 0.0},
        )
        return load_target_cases(path)

    def test_returns_results_keyed_by_case_id(self, tmp_path):
        """Each case id maps to its parsed verdict."""
        cases = self.load_two_cases(tmp_path)
        client = self.make_client('{"t": null, "c": 0.9}')

        results = classify_target_cases(cases, client=client)

        assert set(results) == {"subject-01", "true-01"}
        assert results["subject-01"] == {"t": None, "c": 0.9, "valid": True}

    def test_uses_verifier_model_params(self, tmp_path):
        """Requests go out with the verifier's own model parameters."""
        cases = self.load_two_cases(tmp_path)[:1]
        client = self.make_client('{"t": null, "c": 0.9}')

        classify_target_cases(cases, client=client)

        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["model"] == TARGET_MODEL
        assert kwargs["temperature"] == TARGET_TEMPERATURE
        assert kwargs["max_tokens"] == TARGET_MAX_TOKENS

    def test_default_prompt_carries_case_sentiment(self, tmp_path):
        """The production prompt is built from the case's body and label."""
        cases = self.load_two_cases(tmp_path)[:1]
        client = self.make_client('{"t": null, "c": 0.9}')

        classify_target_cases(cases, client=client)

        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["messages"] == [
            {
                "role": "user",
                "content": build_target_prompt(
                    "They traded Luka for Marvin Bagley", "neg"
                ),
            }
        ]

    def test_uses_prompt_builder(self, tmp_path):
        """The prompt_builder callable receives body and sentiment."""
        cases = self.load_two_cases(tmp_path)[:1]
        client = self.make_client('{"t": null, "c": 0.9}')

        classify_target_cases(
            cases,
            prompt_builder=lambda body, sentiment: f"VARIANT[{sentiment}]: {body}",
            client=client,
        )

        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["messages"] == [
            {
                "role": "user",
                "content": "VARIANT[neg]: They traded Luka for Marvin Bagley",
            }
        ]

    def test_malformed_response_yields_invalid(self, tmp_path):
        """Unparseable model output surfaces as an invalid verdict."""
        cases = self.load_two_cases(tmp_path)[:1]
        client = self.make_client("not json at all")

        results = classify_target_cases(cases, client=client)

        assert results["subject-01"]["valid"] is False


class TestVerdictCorrect:
    @pytest.mark.parametrize(
        "result,expected_target,correct",
        [
            ({"t": "AD", "c": 0.9, "valid": True}, "Anthony Davis", True),
            ({"t": "Anthony Davis", "c": 0.9, "valid": True}, "Anthony Davis", True),
            ({"t": "Luka", "c": 0.9, "valid": True}, "Anthony Davis", False),
            ({"t": None, "c": 0.9, "valid": True}, None, True),
            ({"t": "Nico Harrison", "c": 0.9, "valid": True}, None, True),
            ({"t": None, "c": 0.9, "valid": True}, "Anthony Davis", False),
            ({"t": "AD", "c": 0.9, "valid": True}, None, False),
        ],
    )
    def test_resolves_through_alias_map(
        self, result: dict, expected_target: str | None, correct: bool
    ):
        """The verdict resolves as production would; untracked names are null."""
        assert verdict_correct(result, expected_target, ALIAS_MAP) is correct

    def test_invalid_never_matches_null(self):
        """A parse failure is not a null verdict, even when null is expected."""
        result = {"t": None, "c": 0.0, "valid": False, "raw": "?"}

        assert verdict_correct(result, None, ALIAS_MAP) is False


class TestTargetAccuracyByCategory:
    def test_counts_correct_per_category(self, tmp_path):
        """Correct/total tallies are grouped by case category."""
        path = write_target_cases_file(
            tmp_path,
            [
                make_target_case(),
                make_target_case(id="subject-02", text="Luka got robbed"),
                make_target_case(
                    id="true-01",
                    text="AD showed up to collect a check and dip",
                    attributed_player="Anthony Davis",
                    expected_target="Anthony Davis",
                    category="true_toward",
                ),
            ],
            floors={"subject_not_target": 0.0, "true_toward": 0.0},
        )
        cases = load_target_cases(path)
        results = {
            "subject-01": {"t": None, "c": 0.9, "valid": True},
            "subject-02": {"t": "Luka", "c": 0.8, "valid": True},
            "true-01": {"t": "AD", "c": 0.9, "valid": True},
        }

        accuracy = target_accuracy_by_category(cases, results, ALIAS_MAP)

        assert accuracy == {"subject_not_target": (1, 2), "true_toward": (1, 1)}

    def test_invalid_results_count_incorrect(self, tmp_path):
        """Parse failures count against accuracy, not as null verdicts."""
        path = write_target_cases_file(tmp_path, [make_target_case()])
        cases = load_target_cases(path)
        results = {"subject-01": {"t": None, "c": 0.0, "valid": False, "raw": "?"}}

        accuracy = target_accuracy_by_category(cases, results, ALIAS_MAP)

        assert accuracy == {"subject_not_target": (0, 1)}

    def test_includes_known_miss_cases(self, tmp_path):
        """known_miss cases stay in the totals - floors price them in."""
        path = write_target_cases_file(tmp_path, [make_target_case(known_miss=True)])
        cases = load_target_cases(path)
        results = {"subject-01": {"t": "Luka", "c": 0.9, "valid": True}}

        accuracy = target_accuracy_by_category(cases, results, ALIAS_MAP)

        assert accuracy == {"subject_not_target": (0, 1)}
