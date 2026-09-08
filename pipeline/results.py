"""
Assemble batch classification results into produced frames.

The sentiment stage joins parsed results with filtered comment metadata
(sentiment.parquet, SENTIMENT_SCHEMA); the target stage joins parsed
verdicts with the pool that was sent (sentiment_targets.parquet,
SENTIMENT_TARGETS_SCHEMA). Both enforce their schema at the write boundary.
"""

import json
import logging
from pathlib import Path

import polars as pl

from pipeline.processors import find_player_mentions
from pipeline.schemas import (
    COMMENT_INPUT_SCHEMA,
    RESULTS_SCHEMA,
    SENTIMENT_SCHEMA,
    SENTIMENT_TARGETS_SCHEMA,
    TARGET_POOL_SCHEMA,
    validate_schema,
)
from pipeline.sentiment import parse_response
from pipeline.targets import parse_target_response

logger = logging.getLogger(__name__)


def check_response_models(responses_dir: Path, expected_model: str) -> None:
    """
    Cross-check on-disk response model echoes against the recorded identity.

    Reads each results file up to its first model-bearing line (a batch is
    served by one model, so one echo per file suffices), capped at 1000
    lines so files that never carry the field stay cheap to skip —
    responses downloaded before the field was retained don't have it.
    A file whose first 1000 lines all lack the field (all-errored head)
    is skipped exactly like a field-free legacy file; the cap trades that
    unlikely miss for not re-reading full files.

    Args:
        responses_dir: Directory containing batch_NNN_results.jsonl files.
        expected_model: Model recorded in state at submission.

    Raises:
        RuntimeError: If any response's model differs from expected_model.
        ValueError: If a scanned line is not valid JSON.
    """
    checked = 0
    for results_file in sorted(responses_dir.glob("batch_*_results.jsonl")):
        with open(results_file) as f:
            for line_num, line in enumerate(f):
                if line_num >= 1000:
                    break
                if not line.strip():
                    continue
                try:
                    model = json.loads(line).get("model")
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Malformed JSON in {results_file.name}: {e}"
                    ) from e
                if model is None:
                    continue
                if model != expected_model:
                    raise RuntimeError(
                        f"{results_file.name}: response model {model!r} does not "
                        f"match the identity recorded in state {expected_model!r}"
                    )
                checked += 1
                break
    if checked:
        logger.info(f"Response model cross-check passed for {checked} file(s)")


def _iter_results(responses_dir: Path):
    """
    Yield every downloaded result dict across a stage's results files.

    Args:
        responses_dir: Directory containing batch_NNN_results.jsonl files.

    Yields:
        Result dicts as written by download_results.

    Raises:
        FileNotFoundError: If no results files exist in responses_dir.
        ValueError: If a results file contains malformed JSON.
    """
    results_files = sorted(responses_dir.glob("batch_*_results.jsonl"))
    if not results_files:
        raise FileNotFoundError(f"No results files found in {responses_dir}")

    logger.info(f"Loading results from {len(results_files)} files...")
    for results_file in results_files:
        with open(results_file) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Malformed JSON in {results_file.name}: {e}"
                    ) from e


def build_sentiment_dataframe(
    responses_dir: Path, filtered_path: Path
) -> tuple[pl.DataFrame, list[dict]]:
    """
    Build sentiment DataFrame by joining results with comment metadata.

    mentioned_players is re-derived from body at assembly time under the
    active (or --season override) season's config (#54) — the filtered
    NDJSON's filter-time copy is ignored, so alias fixes reach the parquet
    on any rebuild. Rows whose body no longer matches any tracked player
    are kept with an empty list: population selection stays frozen at
    filter time, only the derivation tracks config. Error-sentiment rows
    get mentions derived too (harmless; aggregation filters them).

    Token and cost accounting happens per batch at download time (see
    summarize_actual_usage in pipeline.batch); this function is a pure
    files-to-DataFrame transform.

    Args:
        responses_dir: Directory containing batch_NNN_results.jsonl files.
        filtered_path: Path to filtered comments JSONL file.

    Returns:
        Tuple of (sentiment DataFrame, list of failed requests).

    Raises:
        FileNotFoundError: If no results files exist in responses_dir.
        ValueError: If a results file contains malformed JSON, or the
            assembled frame does not match SENTIMENT_SCHEMA.
    """
    all_results = []
    failed_requests = []
    normalized_count = 0

    for result in _iter_results(responses_dir):
        if result["result_type"] != "succeeded":
            failed_requests.append(result)
            continue
        parsed = parse_response(result["content"])
        if "p_raw" in parsed:
            normalized_count += 1
            logger.warning(
                f"Normalized list-valued p {parsed['p_raw']!r} -> "
                f"{parsed['p']!r} for {result['custom_id']}"
            )
        all_results.append(
            {
                "id": result["custom_id"],
                "sentiment": parsed["s"],
                "confidence": parsed["c"],
                "sentiment_player": parsed.get("p"),
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
            }
        )

    logger.info(f"Loaded {len(all_results)} successful results")
    if normalized_count:
        logger.warning(f"Normalized {normalized_count} list-valued p field(s)")
    if failed_requests:
        logger.warning(f"Found {len(failed_requests)} failed requests")

    # Create results DataFrame with pinned dtypes (correct even when empty)
    results_df = pl.DataFrame(all_results, schema=RESULTS_SCHEMA)

    # Load comments lazily; the schema pins dtypes and projects away extra keys
    logger.info(f"Loading comments from {filtered_path}...")
    comments_df = pl.scan_ndjson(filtered_path, schema=COMMENT_INPUT_SCHEMA)

    # Join results with comments
    logger.info("Joining results with comments...")
    results_count = len(all_results)
    joined_df = (
        comments_df.join(results_df.lazy(), on="id", how="inner")
        .rename({"id": "comment_id"})
        .with_columns(
            pl.col("body")
            .map_elements(find_player_mentions, return_dtype=pl.List(pl.String))
            .alias("mentioned_players")
        )
        .select(SENTIMENT_SCHEMA.names())
        .collect()
    )

    # Validate join didn't drop rows
    joined_count = len(joined_df)
    if joined_count < results_count:
        dropped = results_count - joined_count
        logger.warning(
            f"Join dropped {dropped} results "
            f"({dropped / results_count * 100:.1f}% - comments may be missing from filtered file)"
        )

    logger.info(f"Final DataFrame: {joined_count} rows")

    validate_schema(joined_df, SENTIMENT_SCHEMA, "sentiment.parquet")

    return joined_df, failed_requests


def build_targets_dataframe(
    responses_dir: Path, pool_path: Path
) -> tuple[pl.DataFrame, list[dict]]:
    """
    Build the verdict sidecar by joining parsed verdicts to the pool.

    The pool records what was sent and why; each succeeded response
    contributes the model's raw target string, confidence, and parse
    validity. A parse failure is kept as a row with valid=False, never
    read as a null verdict. Pool rows whose request did not succeed are
    absent from the sidecar (they are the failed requests).

    Args:
        responses_dir: Directory containing batch_NNN_results.jsonl files.
        pool_path: Path to the pool parquet written at prepare time.

    Returns:
        Tuple of (frame conforming to SENTIMENT_TARGETS_SCHEMA, sorted as
        the pool; list of failed request results).

    Raises:
        FileNotFoundError: If no results files exist in responses_dir.
        ValueError: If a results file contains malformed JSON, the pool
            does not match TARGET_POOL_SCHEMA, or the assembled frame does
            not match SENTIMENT_TARGETS_SCHEMA.
    """
    pool = pl.read_parquet(pool_path)
    validate_schema(pool, TARGET_POOL_SCHEMA, str(pool_path))

    verdicts = []
    failed_requests = []
    invalid_count = 0
    normalized_count = 0
    for result in _iter_results(responses_dir):
        if result["result_type"] != "succeeded":
            failed_requests.append(result)
            continue
        parsed = parse_target_response(result["content"])
        if not parsed["valid"]:
            invalid_count += 1
        if "t_raw" in parsed:
            normalized_count += 1
            logger.warning(
                f"Normalized list-valued t {parsed['t_raw']!r} -> "
                f"{parsed['t']!r} for {result['custom_id']}"
            )
        verdicts.append(
            {
                "comment_id": result["custom_id"],
                "target_raw": parsed["t"],
                "target_confidence": parsed["c"],
                "valid": parsed["valid"],
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
            }
        )

    logger.info(f"Loaded {len(verdicts)} verdicts")
    if invalid_count:
        logger.warning(f"{invalid_count} verdict(s) did not parse (valid=False)")
    if normalized_count:
        logger.warning(f"Normalized {normalized_count} list-valued t field(s)")
    if failed_requests:
        logger.warning(f"Found {len(failed_requests)} failed requests")

    verdict_columns = [
        c for c in SENTIMENT_TARGETS_SCHEMA.names() if c not in pool.columns
    ]
    verdicts_df = pl.DataFrame(
        verdicts,
        schema={
            c: SENTIMENT_TARGETS_SCHEMA[c] for c in ["comment_id", *verdict_columns]
        },
    )

    unknown = verdicts_df.join(pool.select("comment_id"), on="comment_id", how="anti")
    if unknown.height:
        raise ValueError(
            f"{unknown.height} verdict(s) have no pool row (responses and pool "
            f"disagree): {unknown['comment_id'].head(5).to_list()}"
        )

    targets = pool.join(
        verdicts_df, on="comment_id", how="inner", maintain_order="left"
    ).select(SENTIMENT_TARGETS_SCHEMA.names())
    missing = pool.height - targets.height
    if missing:
        logger.warning(
            f"{missing} pool row(s) have no verdict "
            f"({missing / pool.height:.1%} of the pool)"
        )
    logger.info(f"Final sidecar: {targets.height} rows")

    validate_schema(targets, SENTIMENT_TARGETS_SCHEMA, "sentiment_targets.parquet")

    return targets, failed_requests
