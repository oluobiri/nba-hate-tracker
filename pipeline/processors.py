"""
Comment processing pipeline with configurable filter steps.

This module provides reusable filter functions and a pipeline class
for processing Reddit comments through multiple validation stages.
"""

import logging
from collections.abc import Callable

from utils.constants import INVALID_BODY_VALUES, REQUIRED_FIELDS

logger = logging.getLogger(__name__)

# Type alias for step functions
StepFn = Callable[[dict], dict | None]


def has_valid_body(comment: dict) -> dict | None:
    """
    Check if comment has a valid, non-empty body.

    Args:
        comment: Comment dictionary with optional 'body' field.

    Returns:
        Original comment if body is valid, None otherwise.
    """
    body = comment.get("body")
    if not body:
        return None
    if body in INVALID_BODY_VALUES:
        return None
    return comment


def extract_fields(comment: dict) -> dict:
    """
    Extract only the fields needed for downstream processing.

    Args:
        comment: Raw comment dictionary (may have many fields).

    Returns:
        Dictionary with only the REQUIRED_FIELDS needed for analysis.
    """
    return {field: comment.get(field) for field in REQUIRED_FIELDS}


class CommentPipeline:
    """
    Configurable pipeline for processing comments through filter steps.

    Tracks statistics for each step including total processed,
    accepted count, and per-step rejection counts.

    Example:
        pipeline = CommentPipeline()
        pipeline.add_step(is_target_subreddit)
        pipeline.add_step(has_valid_body)
        pipeline.add_step(extract_fields)

        for comment in comments:
            result = pipeline.process(comment)
            if result is not None:
                write(result)

        print(pipeline.stats)
        # {'total': 1000, 'accepted': 150, 'rejected_is_target_subreddit': 800, ...}
    """

    def __init__(self) -> None:
        """Initialize an empty pipeline with zeroed stats."""
        self._steps: list[tuple[str, StepFn]] = []
        self._stats: dict[str, int] = {
            "total": 0,
            "accepted": 0,
        }

    @property
    def stats(self) -> dict[str, int]:
        """
        Return processing statistics.

        Returns:
            Dict with 'total', 'accepted', and 'rejected_<step_name>' keys.
        """
        return self._stats.copy()

    def add_step(self, fn: StepFn, name: str | None = None) -> "CommentPipeline":
        """
        Add a processing step to the pipeline.

        Steps are executed in order. A step that returns None causes
        the comment to be rejected and counted against that step.

        Args:
            fn: Function taking dict, returning dict (pass) or None (reject).
            name: Optional step name for stats. Defaults to fn.__name__.

        Returns:
            Self, for method chaining.
        """
        step_name = name if name is not None else fn.__name__
        self._steps.append((step_name, fn))
        # Pre-initialize rejection counter for this step
        rejection_key = f"rejected_{step_name}"
        if rejection_key not in self._stats:
            self._stats[rejection_key] = 0
        return self

    def process(self, comment: dict) -> dict | None:
        """
        Process a single comment through all pipeline steps.

        Args:
            comment: Raw comment dictionary.

        Returns:
            Processed comment if all steps pass, None if rejected.
        """
        self._stats["total"] += 1
        current = comment

        for step_name, step_fn in self._steps:
            result = step_fn(current)
            if result is None:
                self._stats[f"rejected_{step_name}"] += 1
                return None
            current = result

        self._stats["accepted"] += 1
        return current

    def reset_stats(self) -> None:
        """Reset all statistics to zero."""
        for key in self._stats:
            self._stats[key] = 0
