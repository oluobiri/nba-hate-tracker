"""
Schema contracts for produced data files and cached reference assets.

Single source of truth for column names and dtypes of every file the
pipeline produces. Data dictionary first, enforcement second:

- SENTIMENT_SCHEMA is enforced at the sentiment.parquet write boundary
  (pipeline/results.py) and again as a read-side guard in
  pipeline/aggregation.py.
- The four aggregate-view schemas describe the tabular sections of
  aggregates.json in their parquet-ready shape; they are enforced in
  aggregate_sentiment() before the views are returned for writing.
- ROSTERS_SCHEMA describes the season roster snapshot — a reference
  asset (pipeline ingredient, not a published output) enforced at the
  fetch write boundary (scripts/fetch_rosters.py).
- PLAYERS_SCHEMA describes the Player dimension (players.parquet),
  config curation joined with snapshot facts; enforced in
  aggregate_sentiment() via the unified DASHBOARD_OUTPUT_SCHEMAS loop.
- COMMENT_SAMPLES_SCHEMA describes the comment-samples fact subset
  (comment_samples.parquet): verbatim rows of the fact, selected not
  aggregated; enforced via the same unified loop.

This module must not import from other pipeline modules (it is imported
by them).
"""

import polars as pl

# Bump on any breaking change to a produced-file contract.
SCHEMA_VERSION = 3

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
        "link_id": pl.String,  # post fullname (t3_...), the v3 comment->game bridge
        # Re-derived from body at assembly under the active players.yaml
        # (pipeline/results.py) - NOT projected from the filtered NDJSON
        "mentioned_players": pl.List(pl.String),
        "sentiment": pl.String,  # "pos" | "neg" | "neu" | "error"
        "confidence": pl.Float64,
        "sentiment_player": pl.String,  # nullable
        "input_tokens": pl.Int64,
        "output_tokens": pl.Int64,
    }
)

# --- Construction-side schemas, derived from SENTIMENT_SCHEMA ---------------
# The joined frame is assembled from two file inputs plus one assembly-derived
# column: mentioned_players is recomputed from body at assembly time (#54), so
# neither input schema carries it. Deriving the input schemas from
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
    "link_id",
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
# pipeline/results.py. Doubles as a projection — extra input keys dropped,
# including the NDJSON's filter-time mentioned_players copy (kept in the
# filtered file only as a debugging record of what the filter matched).
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

# --- Reference assets (enforced at the fetch write site) --------------------

# data/<season>/reference/rosters.parquet — one row per rostered player, the
# season roster snapshot from stats.nba.com (pipeline/nba_stats.py). A faithful
# capture of the endpoint: columns the Player-dimension build ignores
# (player_name, team_name/team_abbr, age) stay here deliberately — the
# dimension, not the snapshot, decides what ships. Roster team is
# point-in-time (season-end); see docs/data-model.md §3.
ROSTERS_SCHEMA = pl.Schema(
    {
        "player_id": pl.Int64,
        "player_name": pl.String,
        "team_name": pl.String,
        "team_abbr": pl.String,
        "jersey_number": pl.String,  # string on purpose: "00" is a real number
        "position": pl.String,
        "height": pl.String,  # feet-inches format ("6-8"); bio-line only
        "weight": pl.String,  # pounds-as-string; bio-line only
        "age": pl.Int64,  # frozen at fetch; consumers derive age from birth_date
        "experience": pl.String,  # "R" for rookies, else years as string
        "birth_date": pl.Date,
        "school": pl.String,
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

# View name -> schema for the aggregate *views* (fact-table rollups).
# Keys match aggregate_sentiment() return-dict keys and parquet filenames.
# Deliberately fact-only: dimensions live in DASHBOARD_OUTPUT_SCHEMAS
# below. Membership here does NOT put a view into aggregates.json — the
# script freezes that key set separately as a literal (LEGACY_JSON_VIEWS),
# so future fact views join this mapping without touching the legacy file.
AGGREGATE_VIEW_SCHEMAS: dict[str, pl.Schema] = {
    "player_overall": PLAYER_OVERALL_SCHEMA,
    "player_temporal": PLAYER_TEMPORAL_SCHEMA,
    "player_team": PLAYER_TEAM_SCHEMA,
    "team_overall": TEAM_OVERALL_SCHEMA,
}

# --- Player dimension (enforced in pipeline/aggregation.py) ------------------
# One row per attributed player — the Player dimension the views'
# attributed_player FK references. Materialized as players.parquet; also
# re-serialized to the legacy nested {player: {...}} player_metadata dict in
# aggregates.json (players_to_metadata_dict). The config side is curated in
# config/<season>/players.yaml; the snapshot side LEFT JOINs from the season's
# rosters.parquet on player_id, so snapshot gaps surface as nulls, never
# dropped rows.
# NOTE: roster_team is the *roster* role (who the player plays for),
# role-marked from birth — distinct from the fan-role `team` in
# player_team/team_overall. See docs/data-model.md §2.

PLAYERS_CONFIG_COLUMNS: dict[str, pl.DataType] = {
    "attributed_player": pl.String,
    "roster_team": pl.String,
    "conference": pl.String,
    "player_id": pl.Int64,
    "headshot_url": pl.String,
}

# Joined from ROSTERS_SCHEMA columns of the same name (dtypes derived so
# snapshot and dimension can never drift).
PLAYERS_SNAPSHOT_COLUMNS = [
    "position",
    "birth_date",
    "experience",
    "school",
    "jersey_number",
    "height",
    "weight",
]

PLAYERS_SCHEMA = pl.Schema(
    {
        **PLAYERS_CONFIG_COLUMNS,
        **{col: ROSTERS_SCHEMA[col] for col in PLAYERS_SNAPSHOT_COLUMNS},
    }
)

# --- Team dimension (enforced in pipeline/aggregation.py) -------------------
# One row per franchise — the Team dimension the fan-role `team` FK in
# player_team/team_overall references (and the roster_team FK in players).
# Pure config export from config/teams.yaml; aliases stay config-only (the
# dimension describes and slices, it never selects). PK is bare `team`:
# role-marking (roster_team/fan_team) applies to FK columns on fact tables,
# not the dimension's own key. See docs/data-model.md §2.

TEAMS_SCHEMA = pl.Schema(
    {
        "team": pl.String,
        "abbreviation": pl.String,
        "conference": pl.String,
        "team_id": pl.Int64,
        "logo_url": pl.String,
    }
)

# --- Comment samples: fact subset (enforced in pipeline/aggregation.py) ------
# One row per sampled comment: verbatim fact rows, top-N per player x
# sentiment by score (see build_comment_samples). PK (attributed_player,
# sentiment, rank). body is never truncated. No author, no confidence.
COMMENT_SAMPLES_SCHEMA = pl.Schema(
    {
        "attributed_player": pl.String,  # FK -> players.parquet
        "sentiment": pl.String,  # "pos" | "neg" | "neu", as the fact
        "rank": pl.Int64,  # 1..N within (attributed_player, sentiment)
        "comment_id": pl.String,  # provenance back to the fact
        "link_id": pl.String,  # -> Reddit permalink, with comment_id
        "body": pl.String,  # the receipt, verbatim
        "score": pl.Int64,
        "created_utc": pl.Int64,  # epoch seconds, as the fact
        "fan_team": pl.String,  # nullable; fan role of Team, role-marked
    }
)

# Every table the aggregation stage produces -> its schema, across the three
# classes of produced table: the four fact rollups (AGGREGATE_VIEW_SCHEMAS),
# the Player and Team dimensions, and the comment-samples fact subset.
# Single source for aggregate_sentiment()'s unified validation loop and the
# script's parquet write loop (<name>.parquet).
DASHBOARD_OUTPUT_SCHEMAS: dict[str, pl.Schema] = {
    **AGGREGATE_VIEW_SCHEMAS,
    "players": PLAYERS_SCHEMA,
    "teams": TEAMS_SCHEMA,
    "comment_samples": COMMENT_SAMPLES_SCHEMA,
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
