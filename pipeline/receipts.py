"""The receipts: which comments stand for a player's sentiment.

Home of the comment_samples fact subset and the target-verifier pool.
Both start from one candidate selection, so they are the same
computation by construction: the samples apply the classifier's target
gate; the pool lifts it so named and unnamed rows compete for
verification in one ranking.
"""

import logging
import unicodedata
from pathlib import Path

import polars as pl

from pipeline.schemas import (
    COMMENT_SAMPLES_SCHEMA,
    SENTIMENT_TARGETS_SCHEMA,
    TARGET_POOL_SCHEMA,
    validate_schema,
)
from utils.constants import (
    COMMENT_SAMPLES_MAX_BODY_CHARS,
    COMMENT_SAMPLES_MIN_CONFIDENCE,
    COMMENT_SAMPLES_TOP_N,
    TARGET_POOL_SEED,
    TARGET_POOL_STRATA,
    TARGET_POOL_STRATUM_N,
)
from utils.player_config import load_player_config_version, resolve_sentiment_player

logger = logging.getLogger(__name__)

POLAR_SENTIMENTS = ("pos", "neg")
CELL = ["attributed_player", "sentiment"]
TARGET_STAMP_KEYS = ("classifier_target_model", "classifier_target_prompt_version")


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


def load_target_verdicts(path: Path) -> tuple[pl.DataFrame, dict[str, str | None]]:
    """
    Read the verdict sidecar and check its lineage stamps.

    Warns on players_config_version drift (the pool was built under a
    players.yaml that is no longer active) and on an absent verifier
    identity, the same checks load_attributed_frame makes on the fact.

    Args:
        path: Path to sentiment_targets.parquet.

    Returns:
        Tuple of (frame conforming to SENTIMENT_TARGETS_SCHEMA; the
        classifier_target_model / classifier_target_prompt_version
        stamps, None where absent).

    Raises:
        ValueError: If the parquet does not match SENTIMENT_TARGETS_SCHEMA.
    """
    logger.info(f"Loading target verdicts from {path}")
    verdicts = pl.read_parquet(path)
    validate_schema(verdicts, SENTIMENT_TARGETS_SCHEMA, str(path))

    metadata = pl.read_parquet_metadata(path)
    stamped = metadata.get("players_config_version")
    active = load_player_config_version()
    if stamped is None:
        logger.warning(
            f"{path} carries no players_config_version stamp - "
            f"pool lineage cannot be verified"
        )
    elif stamped != active:
        logger.warning(
            f"{path}: players_config_version drift - pool built under config "
            f"{stamped!r} but active config is {active!r}; verdict coverage "
            f"of the current pool is the measure to watch"
        )
    stamps = {key: metadata.get(key) for key in TARGET_STAMP_KEYS}
    if None in stamps.values():
        logger.warning(
            f"{path} carries no classifier identity stamp - "
            f"verifier lineage cannot be verified"
        )
    logger.info(f"Loaded {verdicts.height:,} verdicts")
    return verdicts, stamps


def _fold_ascii(name: str | None) -> str | None:
    """NFKD-decompose and drop non-ASCII, so 'Dončić' folds to 'Doncic'."""
    if name is None:
        return None
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()


def resolve_verdicts(verdicts: pl.DataFrame, alias_map: dict[str, str]) -> pl.DataFrame:
    """
    Resolve the verifier's raw target strings under an alias map.

    Adds target_player (the canonical name, or null when the verdict is
    null or names no tracked player) and target_player_folded (the same
    lookup after NFKD/ASCII folding). Admission reads target_player;
    the folded column exists for measurement only, so a model-emitted
    accent the config doesn't carry is counted as a mechanical loss
    rather than a screen.

    Args:
        verdicts: Frame conforming to SENTIMENT_TARGETS_SCHEMA.
        alias_map: Lowercase alias -> canonical name.

    Returns:
        The input frame with target_player and target_player_folded
        appended.
    """
    return verdicts.with_columns(
        pl.col("target_raw")
        .map_elements(
            lambda raw: resolve_sentiment_player(raw, alias_map),
            return_dtype=pl.String,
        )
        .alias("target_player"),
        pl.col("target_raw")
        .map_elements(
            lambda raw: resolve_sentiment_player(_fold_ascii(raw), alias_map),
            return_dtype=pl.String,
        )
        .alias("target_player_folded"),
    )


def admit_verified(
    df: pl.DataFrame, verdicts: pl.DataFrame, alias_map: dict[str, str]
) -> pl.DataFrame:
    """
    Keep the polar rows the verifier affirmed; pass neutral rows through.

    A polar row is admitted iff it has a valid sidecar row whose resolved
    target is the attributed player, and the classifier's own target -
    the free gate - does not resolve to a different tracked player. A
    row with no verdict is not admitted (strict posture: thin visibly,
    never misfile). Neutral rows are never verified and are untouched.

    Args:
        df: Attributed frame with attributed_player, sentiment,
            sentiment_player, comment_id.
        verdicts: Resolved sidecar from resolve_verdicts.
        alias_map: Lowercase alias -> canonical name, for the free gate.

    Returns:
        The admitted rows, input columns only.
    """
    polar = df.filter(pl.col("sentiment").is_in(POLAR_SENTIMENTS))
    neutral = df.filter(~pl.col("sentiment").is_in(POLAR_SENTIMENTS))

    affirmed = (
        verdicts.filter(pl.col("valid"))
        .select("comment_id", "target_player")
        .join(polar, on="comment_id", how="inner")
        .filter(pl.col("target_player") == pl.col("attributed_player"))
    )
    classifier_target = pl.col("sentiment_player").map_elements(
        lambda name: resolve_sentiment_player(name, alias_map),
        return_dtype=pl.String,
    )
    admitted = affirmed.filter(
        classifier_target.is_null() | (classifier_target == pl.col("attributed_player"))
    ).select(df.columns)

    logger.info(
        f"verified admission: {polar.height:,} polar rows; {affirmed.height:,} "
        f"affirmed by the verifier, {admitted.height:,} admitted after the "
        f"free gate; {neutral.height:,} neutral rows pass through"
    )
    return pl.concat([admitted, neutral])


def build_comment_samples(
    df: pl.DataFrame,
    *,
    verdicts: pl.DataFrame | None = None,
    alias_map: dict[str, str] | None = None,
    n: int = COMMENT_SAMPLES_TOP_N,
    min_confidence: float = COMMENT_SAMPLES_MIN_CONFIDENCE,
    max_body_chars: int = COMMENT_SAMPLES_MAX_BODY_CHARS,
) -> pl.DataFrame:
    """
    Select the comment samples: top-N receipts per player x sentiment.

    Candidacy and ranking are select_receipt_candidates. Without a
    sidecar the target gate is on: a polar row with no stated target is
    the ambiguity class a receipt can't carry. With a sidecar the
    verifier's verdict is the admission test instead (admit_verified),
    and the classifier's target survives only as the free gate. Neutral
    rows are exempt from every polar gate either way (the classifier
    reports a conventional 0.5 for neu and routinely omits the target
    there). Thin cells are never padded. Bodies are verbatim.

    Args:
        df: Attributed, flair-resolved frame with attributed_player,
            sentiment, sentiment_player, comment_id, link_id, body,
            score, confidence, created_utc, team.
        verdicts: Resolved sidecar from resolve_verdicts; None for the
            gate-only fallback.
        alias_map: Lowercase alias -> canonical name, for the free gate;
            required with verdicts.
        n: Maximum rows per (attributed_player, sentiment) cell.
        min_confidence: Candidacy floor on confidence, pos/neg rows only.
        max_body_chars: Candidacy cap on body length, in characters.

    Returns:
        Frame conforming to COMMENT_SAMPLES_SCHEMA, sorted by
        (attributed_player, sentiment, rank).

    Raises:
        ValueError: If verdicts are given without an alias_map.
    """
    if verdicts is not None:
        if alias_map is None:
            raise ValueError("verdicts require an alias_map for the free gate")
        df = admit_verified(df, verdicts, alias_map)
    return (
        select_receipt_candidates(
            df,
            n=n,
            min_confidence=min_confidence,
            max_body_chars=max_body_chars,
            require_target=verdicts is None,
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
