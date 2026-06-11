"""
Assemble batch classification results into the sentiment DataFrame.

Joins parsed Batch API results with filtered comment metadata and
enforces SENTIMENT_SCHEMA at the sentiment.parquet write boundary.
"""

import json
import logging
from pathlib import Path

import polars as pl

from pipeline.batch import calculate_cost, parse_response
from pipeline.schemas import (
    COMMENT_INPUT_SCHEMA,
    RESULTS_SCHEMA,
    SENTIMENT_SCHEMA,
    validate_schema,
)

logger = logging.getLogger(__name__)


def build_sentiment_dataframe(
    responses_dir: Path, filtered_path: Path, state: dict
) -> tuple[pl.DataFrame, list[dict]]:
    """
    Build sentiment DataFrame by joining results with comment metadata.

    Args:
        responses_dir: Directory containing batch_NNN_results.jsonl files.
        filtered_path: Path to filtered comments JSONL file.
        state: State dict to update with token totals.

    Returns:
        Tuple of (sentiment DataFrame, list of failed requests).

    Raises:
        FileNotFoundError: If no results files exist in responses_dir.
        ValueError: If a results file contains malformed JSON, or the
            assembled frame does not match SENTIMENT_SCHEMA.
    """
    # Load all results
    results_files = sorted(responses_dir.glob("batch_*_results.jsonl"))
    if not results_files:
        raise FileNotFoundError(f"No results files found in {responses_dir}")

    logger.info(f"Loading results from {len(results_files)} files...")

    all_results = []
    failed_requests = []
    total_input_tokens = 0
    total_output_tokens = 0

    for results_file in results_files:
        with open(results_file) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    result = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Malformed JSON in {results_file.name}: {e}"
                    ) from e

                if result["result_type"] == "succeeded":
                    parsed = parse_response(result["content"])
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
                    total_input_tokens += result["input_tokens"]
                    total_output_tokens += result["output_tokens"]
                else:
                    failed_requests.append(result)

    logger.info(f"Loaded {len(all_results)} successful results")
    if failed_requests:
        logger.warning(f"Found {len(failed_requests)} failed requests")

    # Update state with token totals
    state["total_input_tokens"] = total_input_tokens
    state["total_output_tokens"] = total_output_tokens
    state["estimated_cost_usd"] = calculate_cost(
        total_input_tokens, total_output_tokens
    )

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
