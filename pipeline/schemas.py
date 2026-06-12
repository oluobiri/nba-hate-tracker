"""
Schema contracts for produced data files.

Single source of truth for column names and dtypes of every file the
pipeline produces. Data dictionary first, enforcement second:

- SENTIMENT_SCHEMA is enforced at the sentiment.parquet write boundary
  (pipeline/results.py) and again as a read-side guard in
  pipeline/aggregation.py.
- The four aggregate-view schemas describe the tabular sections of
  aggregates.json in their parquet-ready shape; they are enforced in
  aggregate_sentiment() before the views are returned for writing.

This module must not import from other pipeline modules (it is imported
by them).
"""

import polars as pl

# Bump on any breaking change to a produced-file contract.
SCHEMA_VERSION = 1

# data/<season>/processed/sentiment.parquet — one row per classified comment.
SENTIMENT_SCHEMA = pl.Schema(
    {
        "comment_id": pl.String,
        "body": pl.String,
        "author": pl.String,
        "author_flair_text": pl.String,  # nullable
        "author_flair_css_class": pl.String,  # nullable
        "created_utc": pl.Int64,  # epoch seconds
        "score": pl.Int64,
        "mentioned_players": pl.List(pl.String),
        "sentiment": pl.String,  # "pos" | "neg" | "neu" | "error"
        "confidence": pl.Float64,
        "sentiment_player": pl.String,  # nullable
        "input_tokens": pl.Int64,
        "output_tokens": pl.Int64,
    }
)

# --- Construction-side schemas, derived from SENTIMENT_SCHEMA ---------------
# The joined frame is assembled from two inputs. Deriving their schemas from
# SENTIMENT_SCHEMA means a dtype change happens in exactly one place and the
# strict boundary check can never drift from construction.

_COMMENT_SIDE_COLUMNS = [
    "comment_id",
    "body",
    "author",
    "author_flair_text",
    "author_flair_css_class",
    "created_utc",
    "score",
    "mentioned_players",
]
_RESULTS_SIDE_COLUMNS = [
    "sentiment",
    "confidence",
    "sentiment_player",
    "input_tokens",
    "output_tokens",
]

# Filtered-comments NDJSON: comment-side columns. The key column is "id"
# here because the rename to "comment_id" happens after the join in
# pipeline/results.py. Doubles as a projection — extra input keys dropped.
COMMENT_INPUT_SCHEMA = pl.Schema(
    {
        ("id" if col == "comment_id" else col): SENTIMENT_SCHEMA[col]
        for col in _COMMENT_SIDE_COLUMNS
    }
)

# Parsed batch results. The key column is "id" (the request custom_id);
# same rename-after-join story as COMMENT_INPUT_SCHEMA above.
RESULTS_SCHEMA = pl.Schema(
    {
        "id": SENTIMENT_SCHEMA["comment_id"],
        **{col: SENTIMENT_SCHEMA[col] for col in _RESULTS_SIDE_COLUMNS},
    }
)

# --- Aggregate views (enforced in pipeline/aggregation.py) ------------------
# Column order mirrors compute_metrics output: group cols, counts, rates.

_METRIC_COLUMNS: dict[str, pl.DataType] = {
    "neg_count": pl.Int64,  # UInt32 from .len(), cast in compute_metrics
    "pos_count": pl.Int64,
    "neu_count": pl.Int64,
    "comment_count": pl.Int64,
    "neg_rate": pl.Float64,
    "pos_rate": pl.Float64,
    "net_sentiment": pl.Float64,
    "polarization": pl.Float64,
}

PLAYER_OVERALL_SCHEMA = pl.Schema({"attributed_player": pl.String, **_METRIC_COLUMNS})

PLAYER_TEMPORAL_SCHEMA = pl.Schema(
    {
        "attributed_player": pl.String,
        "week": pl.Datetime("us"),  # pl.from_epoch(...).dt.truncate("1w"), no tz
        **_METRIC_COLUMNS,
    }
)

PLAYER_TEAM_SCHEMA = pl.Schema(
    {"attributed_player": pl.String, "team": pl.String, **_METRIC_COLUMNS}
)

TEAM_OVERALL_SCHEMA = pl.Schema(
    {
        "team": pl.String,
        **_METRIC_COLUMNS,
        "abbreviation": pl.String,  # enrichment from config/teams.yaml
        "conference": pl.String,
        "logo_url": pl.String,
    }
)

# View name -> schema, shared by aggregate_sentiment()'s validation loop
# and the aggregation script's parquet write loop. Keys match the
# aggregate_sentiment() return-dict keys and the parquet filenames
# (<view>.parquet).
AGGREGATE_VIEW_SCHEMAS: dict[str, pl.Schema] = {
    "player_overall": PLAYER_OVERALL_SCHEMA,
    "player_temporal": PLAYER_TEMPORAL_SCHEMA,
    "player_team": PLAYER_TEAM_SCHEMA,
    "team_overall": TEAM_OVERALL_SCHEMA,
}


def validate_schema(df: pl.DataFrame, expected: pl.Schema, name: str) -> None:
    """
    Validate a DataFrame against an expected schema, failing fast.

    Strict equality: column names, dtypes, and order must all match.

    Args:
        df: DataFrame to validate.
        expected: Expected schema contract.
        name: Human-readable target name for error messages
            (e.g. "sentiment.parquet").

    Raises:
        ValueError: If the schema does not match. The message names the
            target and enumerates missing columns, extra columns, and
            dtype mismatches (or a column-order mismatch).

    Note:
        Nullable columns must be pinned with schema= at construction —
        an all-null column built without one infers as Null dtype and
        will be reported here as a dtype mismatch.
    """
    actual = df.schema
    if actual == expected:
        return

    problems: list[str] = []
    missing = [col for col in expected if col not in actual]
    extra = [col for col in actual if col not in expected]
    mismatched = [
        f"{col}: expected {expected[col]}, got {actual[col]}"
        for col in expected
        if col in actual and actual[col] != expected[col]
    ]
    if missing:
        problems.append(f"missing columns: {missing}")
    if extra:
        problems.append(f"extra columns: {extra}")
    if mismatched:
        problems.append(f"dtype mismatches: [{'; '.join(mismatched)}]")
    if not problems:  # same names and dtypes, different order
        problems.append(
            f"column order mismatch: expected {expected.names()}, got {actual.names()}"
        )
    raise ValueError(f"Schema validation failed for {name!r}: " + "; ".join(problems))
