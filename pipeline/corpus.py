"""
The corpus at day grain: corpus_daily.parquet.

Materializes the Date dimension at day grain as the funnel's counts
per UTC day: raw comments downloaded, the filtered population
submitted to the classifier, the usable fact rows, and the attributed
rows. Built once from the raw download by scripts.build_corpus_daily,
cached as a reference snapshot, and exported by aggregation, where each
column's sum is asserted against the season's recorded corpus figure
so the corpus numbers have one owner.
"""

import logging
from pathlib import Path
from types import MappingProxyType

import duckdb
import polars as pl

from pipeline.nba_stats import check_snapshot_season
from pipeline.schemas import CORPUS_DAILY_SCHEMA

logger = logging.getLogger(__name__)

RAW_COMMENTS_FILENAME = "r_nba_comments.jsonl"
FILTERED_COMMENTS_FILENAME = "r_nba_player_mentions.jsonl"
CORPUS_DAILY_FILENAME = "corpus_daily.parquet"

# The columns the export asserts against season.yaml's corpus block: the
# recorded stages, by the same name.
OWNED_COLUMNS = ("raw_comments", "population_submitted")


def count_by_day(epochs: pl.DataFrame, name: str) -> pl.DataFrame:
    """
    Count rows per UTC day of their created_utc.

    Args:
        epochs: Frame with a created_utc column (epoch seconds).
        name: Name for the count column.

    Returns:
        Frame (day: Date, <name>: Int64), one row per day present, sorted.
    """
    return (
        epochs.select(
            pl.from_epoch("created_utc", time_unit="s").dt.date().alias("day")
        )
        .group_by("day")
        .agg(pl.len().cast(pl.Int64).alias(name))
        .sort("day")
    )


def count_ndjson_by_day(path: Path, name: str) -> pl.DataFrame:
    """
    Count an NDJSON download's rows per UTC day, projecting created_utc only.

    A streaming pass: DuckDB reads one column of each line, so the raw
    file never accumulates in memory.

    Args:
        path: The .jsonl file (raw comments or the filtered mentions).
        name: Name for the count column.

    Returns:
        Frame (day: Date, <name>: Int64), one row per day present, sorted.
    """
    logger.info(f"Counting {path} by day...")
    epochs = duckdb.sql(
        f"SELECT created_utc FROM read_json('{path}', "
        f"columns={{'created_utc': 'BIGINT'}}, format='newline_delimited')"
    ).pl()
    counts = count_by_day(epochs, name)
    logger.info(f"{counts[name].sum():,} rows over {counts.height} days")
    return counts


def count_fact_by_day(path: Path) -> pl.DataFrame:
    """
    Count the fact's usable and attributed rows per UTC day.

    A fact assembled before attribution was materialized on it carries
    no attributed_player; its attributed count is unknowable until the
    fact is reassembled, so the column is left out (the build carries
    it as null) rather than guessed.

    Args:
        path: Path to sentiment.parquet.

    Returns:
        Frame (day, usable[, attributed]), one row per day present, sorted.
    """
    logger.info(f"Counting {path} by day...")
    scan = pl.scan_parquet(path).filter(pl.col("sentiment") != "error")
    has_attribution = "attributed_player" in scan.collect_schema()
    if not has_attribution:
        logger.warning(
            f"{path} carries no attributed_player (assembled before attribution "
            f"was materialized) - attributed is null until the fact is reassembled"
        )
        return count_by_day(scan.select("created_utc").collect(), "usable")
    fact = scan.select("created_utc", "attributed_player").collect()
    usable = count_by_day(fact, "usable")
    attributed = count_by_day(
        fact.filter(pl.col("attributed_player").is_not_null()), "attributed"
    )
    return usable.join(attributed, on="day", how="left").sort("day")


def build_corpus_daily(
    raw: pl.DataFrame, submitted: pl.DataFrame, fact: pl.DataFrame
) -> pl.DataFrame:
    """
    Assemble the day-grain funnel over the download's UTC extent.

    The grid runs from the earliest to the latest day any source
    carries, so a day with nothing in one stage shows a zero rather than
    a gap and every column sums to its source. A stage no source can
    count (attributed, before the fact carries attribution) is null
    throughout: unknown, not zero.

    Args:
        raw: (day, raw_comments) from count_ndjson_by_day.
        submitted: (day, population_submitted) from count_ndjson_by_day.
        fact: (day, usable[, attributed]) from count_fact_by_day.

    Returns:
        Frame conforming to CORPUS_DAILY_SCHEMA, sorted by day.

    Raises:
        ValueError: If every source is empty (no extent to grid).
    """
    days = pl.concat([raw["day"], submitted["day"], fact["day"]])
    if days.is_empty():
        raise ValueError("corpus_daily: no days in any source; nothing to build")
    grid = pl.date_range(days.min(), days.max(), interval="1d", eager=True).alias("day")
    table = pl.DataFrame({"day": grid})
    for counts in (raw, submitted, fact):
        table = table.join(counts, on="day", how="left")
    table = table.fill_null(0)
    unknown = [col for col in CORPUS_DAILY_SCHEMA.names() if col not in table.columns]
    return (
        table.with_columns(
            pl.lit(None, dtype=CORPUS_DAILY_SCHEMA[col]).alias(col) for col in unknown
        )
        .select(CORPUS_DAILY_SCHEMA.names())
        .cast(dict(CORPUS_DAILY_SCHEMA))
        .sort("day")
    )


def check_corpus_totals(
    corpus_daily: pl.DataFrame, corpus_facts: MappingProxyType | dict
) -> None:
    """
    Assert the owned columns sum to the season's recorded corpus figures.

    season.yaml is the authoritative record of what was downloaded and
    submitted; a table whose sums disagree is wrong, or the record is,
    and either way the build must not ship it silently. An unrecorded
    figure (None) is skipped with a warning.

    Args:
        corpus_daily: Frame conforming to CORPUS_DAILY_SCHEMA.
        corpus_facts: The season's corpus block (load_season_config()["corpus"]).

    Raises:
        ValueError: Naming the column, its sum and the recorded figure.
    """
    for column in OWNED_COLUMNS:
        recorded = corpus_facts.get(column)
        total = int(corpus_daily[column].sum())
        if recorded is None:
            logger.warning(
                f"season.yaml corpus.{column} is unrecorded - corpus_daily sums "
                f"{total:,}; cannot verify the corpus number's owner"
            )
        elif total != recorded:
            raise ValueError(
                f"corpus_daily.{column} sums to {total:,} but season.yaml "
                f"corpus.{column} records {recorded:,}; the corpus number has "
                f"one owner - rebuild the table or correct the record"
            )


def load_corpus_daily(
    reference_dir: Path, corpus_facts: MappingProxyType | dict
) -> tuple[pl.DataFrame, dict]:
    """
    Read the corpus_daily snapshot for export, asserting its totals.

    A missing snapshot degrades to an empty table with a warning, so
    aggregation stays runnable before scripts.build_corpus_daily has
    run for the season.

    Args:
        reference_dir: Season reference directory holding the snapshot.
        corpus_facts: The season's corpus block, the totals' owner.

    Returns:
        (corpus_daily, metadata) where metadata carries
        corpus_daily_processed_at (the snapshot's stamp, or None).

    Raises:
        ValueError: If a snapshot column's sum disagrees with the record.
    """
    path = reference_dir / CORPUS_DAILY_FILENAME
    if not path.exists():
        logger.warning(
            f"{path} not found (run scripts.build_corpus_daily) - "
            f"corpus_daily will be empty"
        )
        return pl.DataFrame(schema=CORPUS_DAILY_SCHEMA), {
            "corpus_daily_processed_at": None
        }

    stamps = check_snapshot_season(path, subject="corpus volume", log=logger)
    corpus_daily = pl.read_parquet(path)
    check_corpus_totals(corpus_daily, corpus_facts)
    logger.info(f"corpus_daily: {corpus_daily.height} days")
    return corpus_daily, {"corpus_daily_processed_at": stamps.get("processed_at")}
