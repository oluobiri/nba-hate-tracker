"""Tests for pipeline.stage (the classifier-stage lookup)."""

import pytest

from pipeline.sentiment import SENTIMENT_STAGE
from pipeline.stage import STAGE_NAMES, ClassifierStage, get_stage
from pipeline.targets import TARGET_STAGE


class TestGetStage:
    """Tests for get_stage."""

    @pytest.mark.parametrize(
        "name,expected",
        [("sentiment", SENTIMENT_STAGE), ("target", TARGET_STAGE)],
    )
    def test_resolves_each_known_stage(self, name: str, expected: ClassifierStage):
        """Verify every name in STAGE_NAMES resolves to its module's instance."""
        assert name in STAGE_NAMES
        assert get_stage(name) is expected

    def test_unknown_name_raises_naming_valid_set(self):
        """Verify an unknown stage fails loudly with the valid names."""
        with pytest.raises(ValueError, match="sentiment"):
            get_stage("nope")

    def test_stamp_keys_are_the_lineage_metadata_keys(self):
        """Verify stamp_keys spell the parquet metadata keys assembly writes."""
        assert SENTIMENT_STAGE.stamp_keys == (
            "classifier_sentiment_model",
            "classifier_sentiment_prompt_version",
        )
        assert TARGET_STAGE.stamp_keys == (
            "classifier_target_model",
            "classifier_target_prompt_version",
        )

    def test_stages_are_distinct_identities(self):
        """Verify the two stages differ in name, model, and sampling contract."""
        assert SENTIMENT_STAGE.name != TARGET_STAGE.name
        assert SENTIMENT_STAGE.model != TARGET_STAGE.model
        assert "temperature" in SENTIMENT_STAGE.sampling_params
        assert "temperature" not in TARGET_STAGE.sampling_params
        assert TARGET_STAGE.sampling_params == {"thinking": {"type": "disabled"}}


class TestClassifierStage:
    """Tests for the ClassifierStage construction contract."""

    def test_sampling_params_may_not_shadow_request_keys(self):
        """Verify a stage whose sampling params set model/max_tokens/messages is rejected."""
        with pytest.raises(ValueError, match="max_tokens"):
            ClassifierStage(
                name="bad",
                model="claude-sonnet-5",
                max_tokens=75,
                sampling_params={"max_tokens": 10, "temperature": 0.0},
                prompt_version="v0",
                prompt_template="{comment_body}",
                build_prompt=str,
                parse_response=lambda text: {},
                input_cost_per_mtok=1.0,
                output_cost_per_mtok=5.0,
                avg_input_tokens=100,
            )
