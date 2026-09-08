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

    def test_stages_are_distinct_identities(self):
        """Verify the two stages differ in name, model, and sampling contract."""
        assert SENTIMENT_STAGE.name != TARGET_STAGE.name
        assert SENTIMENT_STAGE.model != TARGET_STAGE.model
        assert "temperature" in SENTIMENT_STAGE.sampling_params
        assert "temperature" not in TARGET_STAGE.sampling_params
        assert TARGET_STAGE.sampling_params == {"thinking": {"type": "disabled"}}
