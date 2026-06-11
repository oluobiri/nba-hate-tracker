"""Pipeline module for data processing."""

from .aggregation import aggregate_sentiment
from .arctic_shift import ArcticShiftClient
from .batch import (
    build_prompt,
    calculate_cost,
    download_results,
    format_batch_request,
    get_batch_status,
    init_state,
    load_state,
    parse_response,
    save_state,
    submit_batch,
)
from .processors import ProcessingStats, extract_fields, has_valid_body, process_line
from .results import build_sentiment_dataframe
from .schemas import (
    PLAYER_OVERALL_SCHEMA,
    PLAYER_TEAM_SCHEMA,
    PLAYER_TEMPORAL_SCHEMA,
    SCHEMA_VERSION,
    SENTIMENT_SCHEMA,
    TEAM_OVERALL_SCHEMA,
    validate_schema,
)

__all__ = [
    "PLAYER_OVERALL_SCHEMA",
    "PLAYER_TEAM_SCHEMA",
    "PLAYER_TEMPORAL_SCHEMA",
    "SCHEMA_VERSION",
    "SENTIMENT_SCHEMA",
    "TEAM_OVERALL_SCHEMA",
    "ArcticShiftClient",
    "ProcessingStats",
    "aggregate_sentiment",
    "build_prompt",
    "build_sentiment_dataframe",
    "calculate_cost",
    "download_results",
    "extract_fields",
    "format_batch_request",
    "get_batch_status",
    "has_valid_body",
    "init_state",
    "load_state",
    "parse_response",
    "process_line",
    "save_state",
    "submit_batch",
    "validate_schema",
]
