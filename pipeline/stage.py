"""The classifier stage: one frozen identity per LLM classification pass.

A stage is what the batch transport formats requests for, what the
eval harness runs cases through, and what the lineage stamps name.
Each stage module (pipeline.sentiment, pipeline.targets) declares its
own instance; this module only defines the shape and the lookup.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

STAGE_NAMES = ("sentiment", "target")

# Request keys the transport and runner set themselves; a stage's
# sampling params must not shadow them.
_RESERVED_REQUEST_KEYS = frozenset({"model", "max_tokens", "messages"})


@dataclass(frozen=True)
class ClassifierStage:
    """A classifier's identity, sampling contract, and pricing.

    Attributes:
        name: Stage name; doubles as the batches subdirectory.
        model: Model ID sent on every request.
        max_tokens: Output cap per request.
        sampling_params: Extra request params splatted into both the
            batch request and the sync call (e.g. {"temperature": 0.0}
            or {"thinking": {"type": "disabled"}}). Model-specific: some
            models reject temperature.
        prompt_version: Label of the frozen prompt; hash-pinned in tests.
        prompt_template: The frozen template text the label names.
        build_prompt: Renders the template for one comment.
        parse_response: Parses the model's text into the stage's dict.
        input_cost_per_mtok: Batch API input price, USD per million tokens.
        output_cost_per_mtok: Batch API output price, USD per million tokens.
        avg_input_tokens: Measured mean input tokens per request; drives
            the pre-submission cost estimate only.
    """

    name: str
    model: str
    max_tokens: int
    sampling_params: dict[str, Any]
    prompt_version: str
    prompt_template: str
    build_prompt: Callable[..., str]
    parse_response: Callable[[str], dict]
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    avg_input_tokens: int

    @property
    def stamp_keys(self) -> tuple[str, str]:
        """Parquet metadata keys for this stage's model and prompt_version."""
        return (
            f"classifier_{self.name}_model",
            f"classifier_{self.name}_prompt_version",
        )

    def __post_init__(self) -> None:
        """Reject sampling params that would clobber the request's own keys."""
        clash = _RESERVED_REQUEST_KEYS & set(self.sampling_params)
        if clash:
            raise ValueError(
                f"Stage {self.name!r} sampling_params may not set {sorted(clash)}"
            )


def get_stage(name: str) -> ClassifierStage:
    """
    Look up a classifier stage by name.

    Imports lazily: the stage modules import ClassifierStage from here,
    so a module-level registry would be circular.

    Args:
        name: One of STAGE_NAMES.

    Returns:
        The stage's ClassifierStage instance.

    Raises:
        ValueError: If name is not a known stage.
    """
    if name == "sentiment":
        from pipeline.sentiment import SENTIMENT_STAGE

        return SENTIMENT_STAGE
    if name == "target":
        from pipeline.targets import TARGET_STAGE

        return TARGET_STAGE
    raise ValueError(
        f"Unknown classifier stage {name!r} (must be one of {STAGE_NAMES})"
    )
