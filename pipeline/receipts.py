"""The receipts: which comments stand for a player's sentiment.

Home of the comment_samples fact subset and the target-verifier pool.
Both start from one candidate selection, so they are the same
computation by construction: the samples apply the classifier's target
gate; the pool lifts it so named and unnamed rows compete for
verification in one ranking.
"""

import logging

import polars as pl

from pipeline.schemas import COMMENT_SAMPLES_SCHEMA, TARGET_POOL_SCHEMA
from utils.constants import (
    COMMENT_SAMPLES_MAX_BODY_CHARS,
    COMMENT_SAMPLES_MIN_CONFIDENCE,
    COMMENT_SAMPLES_TOP_N,
    TARGET_POOL_SEED,
    TARGET_POOL_STRATA,
    TARGET_POOL_STRATUM_N,
)

logger = logging.getLogger(__name__)

POLAR_SENTIMENTS = ("pos", "neg")
CELL = ["attributed_player", "sentiment"]


def select_receipt_candidates(
    df: pl.DataFrame,
    *,
    n: int,
    min_confidence: float = COMMENT_SAMPLES_MIN_CONFIDENCE,
    max_body_chars: int = COMMENT_SAMPLES_MAX_BODY_CHARS,
    require_target: bool = True,
) -> pl.DataFrame:
    """
    Rank receipt candidates and keep the top n per player x sentiment.

    Candidacy: body no longer than max_body_chars and, for pos/neg,
    confidence at or above min_confidence and (when require_target) a
    named sentiment_player. Neutral rows are exempt from the polar gates.
    Within each cell, duplicate bodies collapse to the best-ranked copy,
    rows rank by score desc (ties: confidence desc, comment_id asc, nulls
    last) and the top n are kept; thin cells are never padded.

    Args:
        df: Attributed frame with attributed_player, sentiment,
            sentiment_player, comment_id, body, score, confidence.
        n: Maximum rows per (attributed_player, sentiment) cell.
        min_confidence: Candidacy floor on confidence, pos/neg rows only.
        max_body_chars: Candidacy cap on body length, in characters.
        require_target: Apply the pos/neg named-sentiment_player gate.

    Returns:
        The candidate rows with a rank column (1..n within the cell), in
        input column order plus rank, unsorted beyond the ranking.
    """
    is_neu = pl.col("sentiment") == "neu"
    passes_floor = is_neu | (pl.col("confidence") >= min_confidence)
    has_target = is_neu | pl.col("sentiment_player").is_not_null()
    if not require_target:
        has_target = pl.lit(True)
    within_cap = pl.col("body").str.len_chars() <= max_body_chars
    candidates = df.filter(passes_floor & has_target & within_cap)
    if df.height:
        below_floor = df.filter(~passes_floor).height
        no_target = df.filter(passes_floor & ~has_target).height
        over_cap = df.filter(passes_floor & has_target & ~within_cap).height
        gate = "on" if require_target else "lifted"
        logger.info(
            f"receipt candidacy (target gate {gate}): {df.height:,} attributed rows; "
            f"{below_floor:,} ({below_floor / df.height:.1%}) removed by the "
            f"pos/neg confidence floor {min_confidence}, "
            f"{no_target:,} ({no_target / df.height:.1%}) removed by the "
            f"pos/neg target gate, "
            f"{over_cap:,} ({over_cap / df.height:.1%}) removed by the "
            f"{max_body_chars}-char body cap; {candidates.height:,} candidates"
        )

    return (
        candidates.sort(
            ["score", "confidence", "comment_id"],
            descending=[True, True, False],
            nulls_last=True,
        )
        .unique(subset=[*CELL, "body"], keep="first", maintain_order=True)
        .with_columns((pl.int_range(pl.len()).over(CELL) + 1).alias("rank"))
        .filter(pl.col("rank") <= n)
    )


def build_target_pool(
    df: pl.DataFrame,
    *,
    k: int,
    stratum_n: int = TARGET_POOL_STRATUM_N,
    seed: int = TARGET_POOL_SEED,
) -> pl.DataFrame:
    """
    Select the comments the target verifier screens, plus evidence strata.

    Candidates are the top-k polar receipts per player x sentiment with
    the target gate lifted, so rows the classifier left unnamed can be
    re-admitted by the verifier. Two seeded random strata of attributed
    polar rows ride the same run as evidence only: named-sentiment_player
    rows (class-2 prevalence at the aggregate level) and NULL rows (the
    class-1 split the resolve_player decision needs). A comment appears
    once; the candidate stratum wins a collision.

    Args:
        df: The attributed frame from load_attributed_frame (unattributed
            rows are ignored).
        k: Candidate-pool depth per cell.
        stratum_n: Rows per random stratum (capped by availability).
        seed: Sampling seed, so the pool is reproducible.

    Returns:
        Frame conforming to TARGET_POOL_SCHEMA, sorted by stratum, cell,
        rank, comment_id.
    """
    polar = df.filter(
        pl.col("attributed_player").is_not_null()
        & pl.col("sentiment").is_in(POLAR_SENTIMENTS)
    )

    candidates = (
        select_receipt_candidates(polar, n=k, require_target=False)
        .with_columns(pl.lit(TARGET_POOL_STRATA[0]).alias("stratum"))
        .select(TARGET_POOL_SCHEMA.names())
    )

    remaining = polar.join(candidates.select("comment_id"), on="comment_id", how="anti")
    named = remaining.filter(pl.col("sentiment_player").is_not_null())
    unnamed = remaining.filter(pl.col("sentiment_player").is_null())
    strata = [
        stratum_df.sample(n=min(stratum_n, stratum_df.height), seed=seed)
        .with_columns(
            pl.lit(label).alias("stratum"), pl.lit(None, dtype=pl.Int64).alias("rank")
        )
        .select(TARGET_POOL_SCHEMA.names())
        for stratum_df, label in (
            (named, TARGET_POOL_STRATA[1]),
            (unnamed, TARGET_POOL_STRATA[2]),
        )
    ]

    pool = pl.concat([candidates, *strata]).sort(
        ["stratum", *CELL, "rank", "comment_id"], nulls_last=True
    )
    counts = pool.group_by("stratum").len().sort("stratum")
    logger.info(
        f"target pool: {pool.height:,} rows over "
        f"{pool['attributed_player'].n_unique()} players; "
        + ", ".join(
            f"{r['stratum']} {r['len']:,}" for r in counts.iter_rows(named=True)
        )
    )
    return pool


def build_comment_samples(
    df: pl.DataFrame,
    *,
    n: int = COMMENT_SAMPLES_TOP_N,
    min_confidence: float = COMMENT_SAMPLES_MIN_CONFIDENCE,
    max_body_chars: int = COMMENT_SAMPLES_MAX_BODY_CHARS,
) -> pl.DataFrame:
    """
    Select the comment samples: top-N receipts per player x sentiment.

    Candidacy and ranking are select_receipt_candidates with the target
    gate on: a polar row with no stated target is the ambiguity class a
    receipt can't carry, while neutral rows are exempt from both polar
    gates (the classifier reports a conventional 0.5 for neu and
    routinely omits the target there). Thin cells are never padded.
    Bodies are verbatim.

    Args:
        df: Attributed, flair-resolved frame with attributed_player,
            sentiment, sentiment_player, comment_id, link_id, body,
            score, confidence, created_utc, team.
        n: Maximum rows per (attributed_player, sentiment) cell.
        min_confidence: Candidacy floor on confidence, pos/neg rows only.
        max_body_chars: Candidacy cap on body length, in characters.

    Returns:
        Frame conforming to COMMENT_SAMPLES_SCHEMA, sorted by
        (attributed_player, sentiment, rank).
    """
    return (
        select_receipt_candidates(
            df, n=n, min_confidence=min_confidence, max_body_chars=max_body_chars
        )
        .rename({"team": "fan_team"})
        .select(COMMENT_SAMPLES_SCHEMA.names())
        .sort([*CELL, "rank"])
    )


def log_comment_samples_diagnostics(
    df_attributed: pl.DataFrame, comment_samples: pl.DataFrame
) -> None:
    """
    Log the multi-mention share of the sampled rows.

    A two-name receipt can read ambiguously under one player's card;
    the share is logged every run so it stays visible.

    Args:
        df_attributed: The attributed frame (carries mentioned_players).
        comment_samples: The selected samples (COMMENT_SAMPLES_SCHEMA).
    """
    if not comment_samples.height:
        logger.info("comment_samples: no rows selected")
        return
    # Semi-join: can't fan out if a comment_id were ever duplicated
    multi = comment_samples.join(
        df_attributed.filter(pl.col("mentioned_players").list.len() > 1).select(
            "comment_id"
        ),
        on="comment_id",
        how="semi",
    ).height
    logger.info(
        f"comment_samples: {comment_samples.height:,} rows selected; "
        f"{multi:,} multi-mention ({multi / comment_samples.height:.1%})"
    )
