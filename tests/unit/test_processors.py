"""Unit tests for pipeline.processors module."""

from pipeline.processors import (
    has_valid_body,
    extract_fields,
    CommentPipeline,
)
from utils.constants import REQUIRED_FIELDS


class TestHasValidBody:
    """Tests for has_valid_body filter function."""

    def test_valid_body_returns_comment(self, valid_nba_comment):
        """Comment with valid body should be returned unchanged."""
        result = has_valid_body(valid_nba_comment)
        assert result == valid_nba_comment

    def test_missing_body_returns_none(self, missing_body_comment):
        """Comment with no body key should return None."""
        result = has_valid_body(missing_body_comment)
        assert result is None

    def test_empty_body_returns_none(self, empty_body_comment):
        """Comment with empty string body should return None."""
        result = has_valid_body(empty_body_comment)
        assert result is None

    def test_deleted_body_returns_none(self, deleted_body_comment):
        """Comment with [deleted] body should return None."""
        result = has_valid_body(deleted_body_comment)
        assert result is None

    def test_removed_body_returns_none(self):
        """Comment with [removed] body should return None."""
        comment = {"id": "test", "body": "[removed]"}
        result = has_valid_body(comment)
        assert result is None


class TestExtractFields:
    """Tests for extract_fields transform function."""

    def test_extracts_all_expected_fields(self, valid_nba_comment):
        """All REQUIRED_FIELDS should be present in output."""
        result = extract_fields(valid_nba_comment)

        assert set(result.keys()) == set(REQUIRED_FIELDS)

    def test_preserves_field_values(self, valid_nba_comment):
        """Field values should match input."""
        result = extract_fields(valid_nba_comment)

        assert result["id"] == valid_nba_comment["id"]
        assert result["body"] == valid_nba_comment["body"]
        assert result["score"] == valid_nba_comment["score"]

    def test_missing_fields_become_none(self):
        """Missing optional fields should be None."""
        minimal = {"id": "test", "body": "hello"}
        result = extract_fields(minimal)

        assert result["id"] == "test"
        assert result["author"] is None
        assert result["score"] is None

    def test_extra_fields_excluded(self):
        """Fields not in schema should not appear in output."""
        comment = {"id": "test", "body": "hi", "extra": "ignored", "gilded": 5}
        result = extract_fields(comment)

        assert "extra" not in result
        assert "gilded" not in result


class TestCommentPipelineInit:
    """Tests for CommentPipeline initialization."""

    def test_empty_pipeline_has_zero_stats(self):
        """New pipeline should have zeroed stats."""
        pipeline = CommentPipeline()

        assert pipeline.stats["total"] == 0
        assert pipeline.stats["accepted"] == 0

    def test_stats_returns_copy(self):
        """Stats property should return a copy, not internal dict."""
        pipeline = CommentPipeline()
        stats1 = pipeline.stats

        stats1["total"] = 999
        assert pipeline.stats["total"] == 0  # Internal not mutated


class TestCommentPipelineAddStep:
    """Tests for CommentPipeline.add_step method."""

    def test_add_step_returns_self(self):
        """add_step should return self for chaining."""
        pipeline = CommentPipeline()
        result = pipeline.add_step(has_valid_body)

        assert result is pipeline

    def test_chaining_multiple_steps(self):
        """Multiple steps can be chained fluently."""
        pipeline = CommentPipeline().add_step(has_valid_body).add_step(extract_fields)

        # Verify both steps were added
        assert len(pipeline._steps) == 2

    def test_step_name_defaults_to_function_name(self):
        """Step name should default to fn.__name__."""
        pipeline = CommentPipeline()
        pipeline.add_step(has_valid_body)

        assert "rejected_has_valid_body" in pipeline.stats

    def test_custom_step_name_used(self):
        """Custom name should override function name."""
        pipeline = CommentPipeline()
        pipeline.add_step(has_valid_body, name="body_validation")

        assert "rejected_body_validation" in pipeline.stats
        assert "rejected_has_valid_body" not in pipeline.stats


class TestCommentPipelineProcess:
    """Tests for CommentPipeline.process method."""

    def test_empty_pipeline_accepts_all(self, valid_nba_comment):
        """Pipeline with no steps should accept everything."""
        pipeline = CommentPipeline()
        result = pipeline.process(valid_nba_comment)

        assert result == valid_nba_comment
        assert pipeline.stats["total"] == 1
        assert pipeline.stats["accepted"] == 1

    def test_passing_comment_increments_accepted(self, valid_nba_comment):
        """Comment passing all steps should increment accepted."""
        pipeline = CommentPipeline()
        pipeline.add_step(has_valid_body)

        result = pipeline.process(valid_nba_comment)

        assert result is not None
        assert pipeline.stats["accepted"] == 1

    def test_failing_step_returns_none(self, deleted_body_comment):
        """Comment failing a step should return None."""
        pipeline = CommentPipeline()
        pipeline.add_step(has_valid_body)

        result = pipeline.process(deleted_body_comment)

        assert result is None

    def test_failing_step_increments_rejection_counter(self, deleted_body_comment):
        """Failed step should increment its rejection counter."""
        pipeline = CommentPipeline()
        pipeline.add_step(has_valid_body)

        pipeline.process(deleted_body_comment)

        assert pipeline.stats["rejected_has_valid_body"] == 1
        assert pipeline.stats["accepted"] == 0

    def test_first_failing_step_gets_credit(self):
        """When multiple steps would fail, first one gets the rejection count."""

        def always_reject(comment: dict) -> dict | None:
            return None

        pipeline = CommentPipeline()
        pipeline.add_step(always_reject, name="step1")
        pipeline.add_step(always_reject, name="step2")

        pipeline.process({"body": "test"})

        assert pipeline.stats["rejected_step1"] == 1
        assert pipeline.stats["rejected_step2"] == 0  # Never reached

    def test_transform_step_modifies_comment(self, valid_nba_comment):
        """Transform steps should pass modified comment to next step."""
        valid_nba_comment["extra_field"] = "should be removed"

        pipeline = CommentPipeline()
        pipeline.add_step(extract_fields)

        result = pipeline.process(valid_nba_comment)

        assert "extra_field" not in result
        assert result["id"] == valid_nba_comment["id"]

    def test_steps_execute_in_order(self):
        """Steps should execute in add order."""
        execution_order = []

        def step_a(c: dict) -> dict:
            execution_order.append("a")
            return c

        def step_b(c: dict) -> dict:
            execution_order.append("b")
            return c

        pipeline = CommentPipeline()
        pipeline.add_step(step_a)
        pipeline.add_step(step_b)

        pipeline.process({"body": "test"})

        assert execution_order == ["a", "b"]


class TestCommentPipelineStatsTracking:
    """Tests for stats accumulation across multiple process calls."""

    def test_stats_accumulate_across_calls(
        self, valid_nba_comment, deleted_body_comment
    ):
        """Stats should accumulate across multiple process() calls."""
        pipeline = CommentPipeline()
        pipeline.add_step(has_valid_body)

        pipeline.process(valid_nba_comment)
        pipeline.process(deleted_body_comment)
        pipeline.process(valid_nba_comment)

        assert pipeline.stats["total"] == 3
        assert pipeline.stats["accepted"] == 2
        assert pipeline.stats["rejected_has_valid_body"] == 1

    def test_reset_stats_zeroes_all(self, valid_nba_comment):
        """reset_stats should zero all counters."""
        pipeline = CommentPipeline()
        pipeline.add_step(has_valid_body)
        pipeline.process(valid_nba_comment)

        pipeline.reset_stats()

        assert pipeline.stats["total"] == 0
        assert pipeline.stats["accepted"] == 0
        assert pipeline.stats["rejected_has_valid_body"] == 0


class TestCommentPipelineIntegration:
    """Integration tests for realistic pipeline configurations."""

    def test_full_pipeline_matches_original_behavior(self, mixed_comments_batch):
        """Pipeline should produce same results as original process_comment."""
        from utils.constants import TARGET_SUBREDDITS

        def is_target_subreddit(comment: dict) -> dict | None:
            subreddit = comment.get("subreddit", "")
            if subreddit.lower() in TARGET_SUBREDDITS:
                return comment
            return None

        pipeline = CommentPipeline()
        pipeline.add_step(is_target_subreddit)
        pipeline.add_step(has_valid_body)
        pipeline.add_step(extract_fields)

        results = [pipeline.process(c) for c in mixed_comments_batch]
        accepted = [r for r in results if r is not None]

        # From fixture: 2 valid (nba, bostonceltics), 1 wrong sub, 1 missing body
        assert pipeline.stats["total"] == 4
        assert pipeline.stats["accepted"] == 2
        assert len(accepted) == 2
