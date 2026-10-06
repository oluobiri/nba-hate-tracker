"""
The accuracy sample: a blind random draw of the attributed population.

The eval suite (pipeline/evaluation.py, pipeline/targets.py) is a
regression tripwire over chosen cases; its pass rate describes the
suite. This module draws rows uniformly at random from the population
the rankings are computed over, hands them out for manual review as a
workbook with no prediction in sight, reads the verdicts back, and
scores the classifier against them. It is the only producer of an
accuracy figure.

The draw is labeled in two groups. Rows chosen freely in a first pass
are a group counted in full; every other row is the ordered group,
labeled top-down in draw order so any labeled prefix is a random
sample of it. The published figure weights the two by their sizes.
Rows set aside from the estimate (verdicts entered after seeing a
model's read) are held out; their weight rides with the ordered group.
"""

import json
import logging
import math
from collections.abc import Mapping
from pathlib import Path

import polars as pl
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from pipeline.lineage import check_config_stamps
from pipeline.schemas import (
    ACCURACY_SAMPLE_SCHEMA,
    AccuracyFigures,
    ClassAgreement,
    ClassMix,
    GroupFigures,
    validate_schema,
)
from pipeline.stage import classifier_stamp_keys
from utils.constants import (
    ACCURACY_CLASS_MIN_N,
    ACCURACY_SAMPLE_N,
    ACCURACY_SAMPLE_SEED,
)

logger = logging.getLogger(__name__)

SENTIMENT_VERDICTS = ("neg", "neu", "pos")
POLAR_VERDICTS = ("neg", "pos")
TARGET_NONE = "none"  # the sentiment is not aimed at a player
TARGET_OTHER = "other"  # aimed at a player the row's list does not offer
REJECT_REASONS = ("alias_false_positive", "unreadable")
CONTEXT_TAG = "ctx"  # in the note: the thread decided the verdict
UNSURE_TAG = "?"  # in the note: a coin flip even with the thread
RUBRIC_VERSION = "v1"

GROUP_FIRST = "first"  # chosen freely, labeled in full
GROUP_ORDERED = "ordered"  # labeled top-down in draw order
GROUP_HELD_OUT = "held_out"  # set aside from the estimate
GROUPS = (GROUP_FIRST, GROUP_ORDERED, GROUP_HELD_OUT)
PASSES_FILENAME = "accuracy_sample.passes.json"

WORKBOOK_FILENAME = "accuracy_sample.xlsx"
SAMPLE_FILENAME = "accuracy_sample.parquet"
LABELS_SHEET = "labels"
CLASSIFIER_SHEET = "classifier"
LISTS_SHEET = "lists"
META_SHEET = "meta"
LABEL_COLUMNS = (
    "comment_id",
    "permalink",
    "post_title",
    "body",
    "sentiment",
    "target",
    "reject",
    "note",
)
CLASSIFIER_COLUMNS = (
    "comment_id",
    "sentiment",
    "confidence",
    "sentiment_player",
    "attributed_player",
    "mentioned_players",
)
COLUMN_WIDTHS = {
    "comment_id": 12,
    "permalink": 10,
    "post_title": 40,
    "body": 90,
    "sentiment": 11,
    "target": 26,
    "reject": 22,
    "note": 40,
}
MENTIONED_SEPARATOR = "|"
PERMALINK = "https://www.reddit.com/r/nba/comments/{}/comment/{}/"
SENTIMENT_STAMP_KEYS = classifier_stamp_keys("sentiment")
RATE_DECIMALS = 4
Z_95 = 1.96
MAX_REPORTED_PROBLEMS = 40

SAMPLE_COLUMNS = (
    "comment_id",
    "permalink",
    "post_title",
    "body",
    "mentioned_players",
    "sentiment",
    "confidence",
    "sentiment_player",
    "attributed_player",
)


def draw_sample(
    df: pl.DataFrame,
    posts: pl.DataFrame | None,
    n: int = ACCURACY_SAMPLE_N,
    seed: int = ACCURACY_SAMPLE_SEED,
) -> pl.DataFrame:
    """
    Draw the sample: n attributed rows, uniformly at random, under a seed.

    The population is the fact's attributed rows with a real label, the
    set every negative rate is computed over. The rows come back in
    random order, so any top-down prefix is itself a random sample. The
    draw is reproducible from the seed as long as the fact's row order
    is; the ids are what the workbook and the parquet carry. Each row
    gets its Reddit permalink and, when the bridge is given, its post
    title.

    Args:
        df: The fact (SENTIMENT_SCHEMA columns; error rows may be present).
        posts: The post bridge (post_id, title), or None for no titles.
        n: Rows to draw.
        seed: Sampling seed.

    Returns:
        A frame of SAMPLE_COLUMNS.

    Raises:
        ValueError: If the population holds fewer than n rows.
    """
    population = df.filter(
        pl.col("attributed_player").is_not_null() & (pl.col("sentiment") != "error")
    )
    if population.height < n:
        raise ValueError(
            f"attributed population holds {population.height:,} rows, fewer "
            f"than the {n:,} requested"
        )
    sample = population.sample(n=n, seed=seed).select(
        "comment_id",
        "link_id",
        "body",
        "mentioned_players",
        "sentiment",
        "confidence",
        "sentiment_player",
        "attributed_player",
    )
    sample = sample.with_columns(
        pl.format(
            PERMALINK,
            pl.col("link_id").str.replace("^t3_", ""),
            pl.col("comment_id"),
        ).alias("permalink")
    )
    if posts is None:
        sample = sample.with_columns(pl.lit(None, dtype=pl.String).alias("post_title"))
    else:
        titles = posts.select(
            pl.col("post_id").alias("link_id"), pl.col("title").alias("post_title")
        )
        sample = sample.join(titles, on="link_id", how="left", maintain_order="left")

    mix = {
        label: sample.filter(pl.col("sentiment") == label).height
        for label in SENTIMENT_VERDICTS
    }
    logger.info(
        f"drew {sample.height:,} of {population.height:,} attributed rows "
        f"(seed {seed}); predicted mix "
        + ", ".join(f"{label} {count:,}" for label, count in mix.items())
    )
    thin = [label for label, count in mix.items() if count < ACCURACY_CLASS_MIN_N]
    if thin:
        logger.warning(
            f"predicted class(es) {thin} fall under {ACCURACY_CLASS_MIN_N} rows in "
            f"the draw: per-class figures will be wide; consider a stratified draw"
        )
    return sample.select(*SAMPLE_COLUMNS)


def target_options(mentioned_players: list[str]) -> tuple[str, ...]:
    """
    The target list a row offers: its mentioned players, then none and other.

    Args:
        mentioned_players: The row's tracked mentions, canonical names.

    Returns:
        The dropdown's values in order.
    """
    return (*mentioned_players, TARGET_NONE, TARGET_OTHER)


def _list_validation(formula: str) -> DataValidation:
    """A dropdown that refuses a typed value outside its list, blank allowed."""
    return DataValidation(
        type="list",
        formula1=formula,
        allow_blank=True,
        showErrorMessage=True,
        errorStyle="stop",
        errorTitle="Not in the list",
        error="Pick a value from the dropdown, or leave the cell blank.",
    )


def write_workbook(sample: pl.DataFrame, path: Path, stamps: Mapping[str, str]) -> None:
    """
    Write the labeling workbook.

    The labels sheet shows the comment and nothing the classifier said:
    id, permalink, post title, body, then three list-validated verdict
    columns and a note. The target list is per row (that comment's
    mentioned players, none, other), served from a hidden lists sheet.
    The classifier's side and the draw's stamps sit on hidden sheets
    for the import to join back by comment id.

    Args:
        sample: Frame from draw_sample.
        path: Destination .xlsx.
        stamps: Draw metadata (config, classifier, seed, n, drawn_at).
    """
    workbook = Workbook()
    labels = workbook.active
    labels.title = LABELS_SHEET
    labels.append(list(LABEL_COLUMNS))
    for cell in labels[1]:
        cell.font = Font(bold=True)
    labels.freeze_panes = "A2"
    for index, name in enumerate(LABEL_COLUMNS, start=1):
        labels.column_dimensions[get_column_letter(index)].width = COLUMN_WIDTHS[name]

    lists = workbook.create_sheet(LISTS_SHEET)
    lists.sheet_state = "hidden"
    classifier = workbook.create_sheet(CLASSIFIER_SHEET)
    classifier.sheet_state = "hidden"
    classifier.append(list(CLASSIFIER_COLUMNS))
    meta = workbook.create_sheet(META_SHEET)
    meta.sheet_state = "hidden"
    for key, value in stamps.items():
        meta.append([key, value])

    last_row = sample.height + 1
    sentiment_validation = _list_validation(f'"{",".join(SENTIMENT_VERDICTS)}"')
    reject_validation = _list_validation(f'"{",".join(REJECT_REASONS)}"')
    labels.add_data_validation(sentiment_validation)
    labels.add_data_validation(reject_validation)
    sentiment_validation.add(f"E2:E{last_row}")
    reject_validation.add(f"G2:G{last_row}")

    list_validations: dict[tuple[str, ...], DataValidation] = {}
    wrap = Alignment(wrap_text=True, vertical="top")
    for row_number, row in enumerate(sample.iter_rows(named=True), start=2):
        options = target_options(row["mentioned_players"])
        validation = list_validations.get(options)
        if validation is None:
            lists.append(list(options))
            list_row = len(list_validations) + 1
            last_column = get_column_letter(len(options))
            validation = _list_validation(
                f"{LISTS_SHEET}!$A${list_row}:${last_column}${list_row}"
            )
            labels.add_data_validation(validation)
            list_validations[options] = validation
        validation.add(f"F{row_number}")

        labels.append([row["comment_id"], "open", row["post_title"], row["body"]])
        labels.cell(row=row_number, column=1).number_format = "@"
        link = labels.cell(row=row_number, column=2)
        link.hyperlink = row["permalink"]
        link.style = "Hyperlink"
        labels.cell(row=row_number, column=3).alignment = wrap
        labels.cell(row=row_number, column=4).alignment = wrap

        classifier.append(
            [
                row["comment_id"],
                row["sentiment"],
                row["confidence"],
                row["sentiment_player"],
                row["attributed_player"],
                MENTIONED_SEPARATOR.join(row["mentioned_players"]),
            ]
        )
    workbook.save(path)


def load_passes(path: Path) -> dict[str, list[str]] | None:
    """
    Read the group assignment beside the workbook, if any.

    The file names the comment ids of the first pass and of the held-out
    rows; every other drawn row is the ordered group. Without the file
    the whole draw is the ordered group.

    Args:
        path: Path to the passes JSON.

    Returns:
        {"first": [...], "held_out": [...]} (missing keys read as empty),
        or None when the file is absent.

    Raises:
        ValueError: If an id appears in both lists.
    """
    if not path.exists():
        return None
    document = json.loads(path.read_text())
    passes = {
        GROUP_FIRST: [str(c) for c in document.get(GROUP_FIRST, [])],
        GROUP_HELD_OUT: [str(c) for c in document.get(GROUP_HELD_OUT, [])],
    }
    both = set(passes[GROUP_FIRST]) & set(passes[GROUP_HELD_OUT])
    if both:
        raise ValueError(f"{path}: ids in both first and held_out: {sorted(both)[:5]}")
    return passes


def _text(value: object) -> str | None:
    """A cell as stripped text; None for an empty cell."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _header_matches(values: tuple, expected: tuple[str, ...]) -> bool:
    """The sheet's header equals the contract, ignoring trailing empty columns."""
    cells = [_text(value) for value in values]
    while cells and cells[-1] is None:
        cells.pop()
    return tuple(cells) == expected


def read_workbook(
    path: Path, passes: Mapping[str, list[str]] | None = None
) -> tuple[pl.DataFrame, dict[str, str]]:
    """
    Read the workbook back as the accuracy sample, labeled rows and not.

    Every drawn row comes back, in draw order, with its group. A labeled
    row needs a sentiment and a target from its own list, or a known
    reject reason; the ordered group must be labeled top-down, so an
    unlabeled ordered row above a labeled one is refused. Problems are
    reported by sheet row, all at once.

    Args:
        path: The .xlsx written by write_workbook, filled in or partly.
        passes: Group assignment from load_passes; None puts every row
            in the ordered group.

    Returns:
        (frame under ACCURACY_SAMPLE_SCHEMA in draw order; the stamps
        from the meta sheet).

    Raises:
        ValueError: If a sheet or header is missing, a passes id is not
            in the draw, or any row fails the checks; the message lists
            the rows.
    """
    workbook = load_workbook(path, read_only=True, data_only=True)
    for sheet in (LABELS_SHEET, CLASSIFIER_SHEET, META_SHEET):
        if sheet not in workbook.sheetnames:
            raise ValueError(f"{path}: sheet {sheet!r} is missing")

    stamps = {
        str(key): str(value)
        for key, value in workbook[META_SHEET].iter_rows(values_only=True)
        if key is not None and value is not None
    }

    classifier_rows = workbook[CLASSIFIER_SHEET].iter_rows(values_only=True)
    if not _header_matches(next(classifier_rows, ()), CLASSIFIER_COLUMNS):
        raise ValueError(f"{path}: the {CLASSIFIER_SHEET} sheet's header was changed")
    drawn: dict[str, dict] = {}
    for values in classifier_rows:
        row = dict(zip(CLASSIFIER_COLUMNS, values))
        if row["comment_id"] is None:
            continue
        mentioned = _text(row["mentioned_players"])
        row["mentioned_players"] = (
            mentioned.split(MENTIONED_SEPARATOR) if mentioned else []
        )
        drawn[str(row["comment_id"])] = row

    groups = dict.fromkeys(drawn, GROUP_ORDERED)
    for group in (GROUP_FIRST, GROUP_HELD_OUT):
        for comment_id in (passes or {}).get(group, []):
            if comment_id not in drawn:
                raise ValueError(f"{path}: {group} id {comment_id} is not in the draw")
            groups[comment_id] = group

    label_rows = workbook[LABELS_SHEET].iter_rows(values_only=True)
    if not _header_matches(next(label_rows, ()), LABEL_COLUMNS):
        raise ValueError(f"{path}: the {LABELS_SHEET} sheet's header was changed")

    problems: list[str] = []
    labels: dict[str, dict] = {}
    for row_number, values in enumerate(label_rows, start=2):
        row = {name: _text(value) for name, value in zip(LABEL_COLUMNS, values)}
        comment_id = row["comment_id"]
        if comment_id is None:
            if any(row[name] for name in ("sentiment", "target", "reject", "note")):
                problems.append(f"row {row_number}: verdicts without a comment_id")
            continue
        if comment_id not in drawn:
            problems.append(f"row {row_number}: {comment_id} is not in the draw")
            continue
        if comment_id in labels:
            problems.append(f"row {row_number}: {comment_id} appears twice")
            continue
        row["row"] = row_number
        labels[comment_id] = row

        reject = row["reject"]
        labeled = bool(row["sentiment"] or row["target"] or reject)
        if not labeled:
            continue
        if reject is not None:
            if reject not in REJECT_REASONS:
                problems.append(
                    f"row {row_number}: reject {reject!r} is not one of "
                    f"{list(REJECT_REASONS)}"
                )
            continue
        if row["sentiment"] not in SENTIMENT_VERDICTS:
            problems.append(
                f"row {row_number}: sentiment {row['sentiment']!r} is not one of "
                f"{list(SENTIMENT_VERDICTS)}"
            )
        options = target_options(drawn[comment_id]["mentioned_players"])
        if row["target"] not in options:
            problems.append(
                f"row {row_number}: target {row['target']!r} is not one of "
                f"{list(options)}"
            )

    missing = [comment_id for comment_id in drawn if comment_id not in labels]
    if missing:
        problems.append(
            f"{len(missing)} drawn row(s) are absent from the {LABELS_SHEET} sheet: "
            + ", ".join(missing[:10])
            + (", ..." if len(missing) > 10 else "")
        )

    # The ordered group is a prefix sample only if nothing was skipped
    skipped: list[int] = []
    seen_unlabeled: list[int] = []
    for comment_id in drawn:
        if groups[comment_id] != GROUP_ORDERED or comment_id not in labels:
            continue
        row = labels[comment_id]
        if row["sentiment"] or row["target"] or row["reject"]:
            skipped.extend(seen_unlabeled)
            seen_unlabeled = []
        else:
            seen_unlabeled.append(row["row"])
    if skipped:
        problems.append(
            f"{len(skipped)} ordered row(s) were skipped (the ordered group is "
            f"labeled top-down, no gaps): rows "
            + ", ".join(str(r) for r in skipped[:15])
            + (", ..." if len(skipped) > 15 else "")
        )

    if problems:
        shown = problems[:MAX_REPORTED_PROBLEMS]
        more = len(problems) - len(shown)
        raise ValueError(
            f"{path}: {len(problems)} problem(s) in the {LABELS_SHEET} sheet:\n  "
            + "\n  ".join(shown)
            + (f"\n  ... and {more} more" if more else "")
        )

    records = []
    for position, (comment_id, prediction) in enumerate(drawn.items()):
        label = labels[comment_id]
        rejected = label["reject"] is not None
        labeled = bool(label["sentiment"] or label["target"] or rejected)
        note = label["note"]
        records.append(
            {
                "comment_id": comment_id,
                "group": groups[comment_id],
                "position": position,
                "mention_count": len(prediction["mentioned_players"]),
                "sentiment": prediction["sentiment"],
                "confidence": float(prediction["confidence"]),
                "sentiment_player": _text(prediction["sentiment_player"]),
                "attributed_player": prediction["attributed_player"],
                "labeled": labeled,
                "label_sentiment": None if rejected else label["sentiment"],
                "label_target": None if rejected else label["target"],
                "reject": label["reject"],
                "needed_context": bool(note and CONTEXT_TAG in note.lower()),
                "unsure": bool(note and UNSURE_TAG in note),
                "note": note,
            }
        )
    frame = pl.DataFrame(records, schema=ACCURACY_SAMPLE_SCHEMA)
    validate_schema(frame, ACCURACY_SAMPLE_SCHEMA, str(path))
    return frame, stamps


def _rate(numerator: float, denominator: float) -> float | None:
    """A share rounded for the manifest; None over an empty denominator."""
    if not denominator:
        return None
    return round(numerator / denominator, RATE_DECIMALS)


def unlabeled_figures() -> AccuracyFigures:
    """The figures block when no labeled sample exists: every figure null."""
    return {
        "labeled": False,
        "drawn": None,
        "scored": None,
        "rejected": None,
        "seed": None,
        "drawn_at": None,
        "rubric": None,
        "groups": None,
        "sentiment_agreement": None,
        "sentiment_margin": None,
        "target_agreement": None,
        "target_margin": None,
        "joint_agreement": None,
        "joint_margin": None,
        "by_class": None,
        "class_mix": None,
        "context_share": None,
        "unsure_share": None,
        "reject_share": None,
    }


# Scoring predicates over a scored (labeled, not rejected) row.
_SENTIMENT_OK = pl.col("sentiment") == pl.col("label_sentiment")
_TARGET_OK = pl.col("attributed_player") == pl.col("label_target")
_POLAR = pl.col("label_sentiment").is_in(POLAR_VERDICTS)
# A row naming several players whose manual target is another listed
# player judged a different player's sentiment: not comparable
_COMPARABLE = (
    (pl.col("mention_count") <= 1)
    | _TARGET_OK
    | pl.col("label_target").is_in([TARGET_NONE, TARGET_OTHER])
)
_JOINT_OK = _SENTIMENT_OK & _COMPARABLE & (_TARGET_OK | ~_POLAR)


def _weighted_means(
    groups: Mapping[str, pl.DataFrame],
    weights: Mapping[str, float],
    value: pl.Expr,
    denominator: pl.Expr,
) -> tuple[float, float] | None:
    """
    The two weighted per-row means a figure is the ratio of.

    Args:
        groups: Scored rows per estimating group.
        weights: Group -> population weight (sums to 1).
        value: Row predicate or signed value, counted on denominator rows.
        denominator: Row predicate the figure is over.

    Returns:
        (mean of the value, mean of the denominator), each group weighted
        by its size; None when a group has no scored row.
    """
    inside = denominator.cast(pl.Float64)
    top = bottom = 0.0
    for name, frame in groups.items():
        if not frame.height:
            return None
        means = frame.select(
            (value.cast(pl.Float64) * inside).mean().alias("top"),
            inside.mean().alias("bottom"),
        ).row(0)
        top += weights[name] * means[0]
        bottom += weights[name] * means[1]
    return top, bottom


def _weighted(
    groups: Mapping[str, pl.DataFrame],
    weights: Mapping[str, float],
    value: pl.Expr,
    denominator: pl.Expr,
) -> float | None:
    """
    A share over scored rows, each estimating group weighted by its size.

    The share is the ratio of two weighted means (rows meeting the
    predicate, rows meeting the denominator), so a conditional figure
    like a class precision stays a proper population estimate. A signed
    value in place of the predicate gives its weighted mean.

    Args:
        groups: Scored rows per estimating group.
        weights: Group -> population weight (sums to 1).
        value: Row predicate counted in the numerator, or a signed value.
        denominator: Row predicate counted in the denominator.

    Returns:
        The rounded share, or None when no group has a denominator row.
    """
    means = _weighted_means(groups, weights, value, denominator)
    return None if means is None else _rate(*means)


def _margin(
    groups: Mapping[str, pl.DataFrame],
    weights: Mapping[str, float],
    sizes: Mapping[str, int],
    drawn: int,
    value: pl.Expr,
    denominator: pl.Expr,
) -> float | None:
    """
    Half-width of the 95% interval on a weighted share or mean.

    Two-phase sampling: the draw's own variance over the population,
    plus the ordered group's sampling variance within its part of the
    draw, finite-population corrected. The first pass is a census of
    its part and adds no second-phase term. Both terms are taken over
    each row's pull on the figure (its value less the figure, on the
    rows the figure is over), so a conditional share is as wide as its
    own rows make it.

    Args:
        groups: Scored rows per estimating group.
        weights: Group -> population weight.
        sizes: Group -> rows of the draw the group stands for.
        drawn: Rows in the draw.
        value: Row predicate the share counts, or a signed value.
        denominator: Row predicate the figure is over.

    Returns:
        The rounded half-width, or None when the figure is undefined.
    """
    means = _weighted_means(groups, weights, value, denominator)
    if means is None or not means[1]:
        return None
    top, bottom = means
    pull = (
        (value.cast(pl.Float64) - top / bottom) * denominator.cast(pl.Float64) / bottom
    )
    variance = 0.0
    for name, frame in groups.items():
        pulls = frame.select(pull.alias("pull"))["pull"]
        variance += weights[name] * (pulls**2).mean() / drawn
        if name == GROUP_ORDERED:
            fraction = min(frame.height / sizes[GROUP_ORDERED], 1.0)
            variance += (
                weights[name] ** 2 * pulls.var(ddof=0) / frame.height * (1 - fraction)
            )
    return round(Z_95 * math.sqrt(variance), RATE_DECIMALS)


def _group_figures(frame: pl.DataFrame, weight: float) -> GroupFigures:
    """One group's unweighted figures and its weight in the estimate."""
    labeled = frame.filter(pl.col("labeled"))
    scored = labeled.filter(pl.col("reject").is_null())
    comparable = scored.filter(_COMPARABLE)
    polar = scored.filter(_POLAR)
    return {
        "size": frame.height,
        "weight": round(weight, RATE_DECIMALS),
        "labeled": labeled.height,
        "rejected": labeled.height - scored.height,
        "scored": scored.height,
        "sentiment_agreement": _rate(
            comparable.filter(_SENTIMENT_OK).height, comparable.height
        ),
        "target_agreement": _rate(polar.filter(_TARGET_OK).height, polar.height),
        "joint_agreement": _rate(scored.filter(_JOINT_OK).height, scored.height),
    }


def score_sample(
    sample: pl.DataFrame,
    *,
    seed: int | None,
    drawn_at: str | None,
    rubric: str | None = RUBRIC_VERSION,
) -> AccuracyFigures:
    """
    Score the classifier against the manual verdicts.

    Rejected and unlabeled rows are excluded before anything is counted.
    Sentiment agreement is the label match over comparable rows; target
    agreement is the manual target being the attributed player, over the
    rows the manual read calls positive or negative; joint is both on
    the same row (a neutral row needs only the label). Each class's
    share is given for both sides with the gap between them and its
    margin, paired by row. Per class:
    precision and recall of the label, and toward_precision, labeled so
    and about the attributed player, of the predicted, which is the
    figure a negative rate rests on. Every published share weights the
    first pass by its size and the ordered group by every row outside
    the first pass; held-out rows are reported per group and never
    estimate.

    Args:
        sample: Frame under ACCURACY_SAMPLE_SCHEMA.
        seed: The draw's seed, for the block.
        drawn_at: The draw's date, for the block.
        rubric: The labeling rubric's version, for the block.

    Returns:
        The AccuracyFigures block; unlabeled when no row is labeled.
    """
    if not sample.filter(pl.col("labeled")).height:
        return unlabeled_figures()

    drawn = sample.height
    sizes = {name: sample.filter(pl.col("group") == name).height for name in GROUPS}
    # The ordered group stands for every row outside the first pass
    spans = {
        GROUP_FIRST: sizes[GROUP_FIRST],
        GROUP_ORDERED: drawn - sizes[GROUP_FIRST],
    }
    weights = {name: spans[name] / drawn for name in spans}

    scored_by_group = {
        name: sample.filter(
            (pl.col("group") == name) & pl.col("labeled") & pl.col("reject").is_null()
        )
        for name in (GROUP_FIRST, GROUP_ORDERED)
    }
    estimating = {name: f for name, f in scored_by_group.items() if spans[name]}
    labeled_by_group = {
        name: sample.filter((pl.col("group") == name) & pl.col("labeled"))
        for name in estimating
    }

    def share(predicate: pl.Expr, denominator: pl.Expr = pl.lit(True)) -> float | None:
        return _weighted(estimating, weights, predicate, denominator)

    def margin(predicate: pl.Expr, denominator: pl.Expr = pl.lit(True)) -> float | None:
        return _margin(estimating, weights, spans, drawn, predicate, denominator)

    by_class: dict[str, ClassAgreement] = {}
    class_mix: dict[str, ClassMix] = {}
    scored_all = pl.concat(scored_by_group.values())
    for label in SENTIMENT_VERDICTS:
        predicted = pl.col("sentiment") == label
        manual = pl.col("label_sentiment") == label
        by_class[label] = {
            "predicted": scored_all.filter(predicted).height,
            "labeled": scored_all.filter(manual).height,
            "precision": share(manual, predicted & _COMPARABLE),
            "recall": share(predicted, manual & _COMPARABLE),
            "toward_precision": share(manual & _TARGET_OK, predicted & _COMPARABLE),
        }
        gap = predicted.cast(pl.Int8) - manual.cast(pl.Int8)
        class_mix[label] = {
            "classifier": share(predicted),
            "manual": share(manual),
            "gap": share(gap),
            "gap_margin": margin(gap),
        }

    return {
        "labeled": True,
        "drawn": drawn,
        "scored": scored_all.height,
        "rejected": sum(frame.height for frame in labeled_by_group.values())
        - scored_all.height,
        "seed": seed,
        "drawn_at": drawn_at,
        "rubric": rubric,
        "groups": {
            name: _group_figures(
                sample.filter(pl.col("group") == name), weights.get(name, 0.0)
            )
            for name in GROUPS
            if sizes[name]
        },
        "sentiment_agreement": share(_SENTIMENT_OK, _COMPARABLE),
        "sentiment_margin": margin(_SENTIMENT_OK, _COMPARABLE),
        "target_agreement": share(_TARGET_OK, _POLAR),
        "target_margin": margin(_TARGET_OK, _POLAR),
        "joint_agreement": share(_JOINT_OK),
        "joint_margin": margin(_JOINT_OK),
        "by_class": by_class,
        "class_mix": class_mix,
        "context_share": share(pl.col("needed_context")),
        "unsure_share": share(pl.col("unsure")),
        "reject_share": _weighted(
            labeled_by_group, weights, pl.col("reject").is_not_null(), pl.lit(True)
        ),
    }


def load_accuracy_sample(
    path: Path | None, fact_stamps: Mapping[str, str | None]
) -> AccuracyFigures:
    """
    Score the labeled sample on disk, or report that there is none.

    The sample's players-config stamp is drift-checked (the target
    options were built under it) and its classifier identity is compared
    with the fact's: a figure describes the classifier it was labeled
    against, so a mismatch is warned, never hidden.

    Args:
        path: Path to accuracy_sample.parquet, or None.
        fact_stamps: The fact's classifier_sentiment stamps.

    Returns:
        The AccuracyFigures block; unlabeled when the file is absent or
        holds no verdict.

    Raises:
        ValueError: If the file does not conform to ACCURACY_SAMPLE_SCHEMA.
    """
    if path is None or not path.exists():
        logger.warning(
            f"no accuracy sample at {path}: the manifest carries no accuracy figure"
        )
        return unlabeled_figures()

    metadata = pl.read_parquet_metadata(path)
    check_config_stamps(
        path,
        metadata,
        "accuracy_sample",
        subject="accuracy sample",
        remedy="the target options were offered under another alias map; the "
        "figure stands for the config it was labeled under",
        log=logger,
    )
    for key in SENTIMENT_STAMP_KEYS:
        if metadata.get(key) != fact_stamps.get(key):
            logger.warning(
                f"{path}: {key} is {metadata.get(key)!r} but the fact carries "
                f"{fact_stamps.get(key)!r}; the accuracy figure describes the "
                f"classifier it was labeled against, not this fact - redraw and "
                f"relabel"
            )

    sample = pl.read_parquet(path)
    validate_schema(sample, ACCURACY_SAMPLE_SCHEMA, str(path))
    seed = metadata.get("sample_seed")
    figures = score_sample(
        sample,
        seed=int(seed) if seed is not None else None,
        drawn_at=metadata.get("drawn_at"),
        rubric=metadata.get("rubric_version"),
    )
    if figures["labeled"]:
        log_figures(figures)
    else:
        logger.warning(f"{path} holds no verdict: the manifest carries no figure")
    return figures


def log_figures(figures: AccuracyFigures) -> None:
    """
    Log a labeled figures block in one readable pass.

    Args:
        figures: A labeled AccuracyFigures block.
    """

    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.1%}"

    def pm(value: float | None, half: float | None) -> str:
        return pct(value) if half is None else f"{pct(value)} ± {pct(half)}"

    logger.info(
        f"accuracy sample: {figures['scored']:,} scored of {figures['drawn']:,} drawn "
        f"({figures['rejected']:,} rejected); sentiment "
        f"{pm(figures['sentiment_agreement'], figures['sentiment_margin'])}, target "
        f"{pm(figures['target_agreement'], figures['target_margin'])}, joint "
        f"{pm(figures['joint_agreement'], figures['joint_margin'])}"
    )
    for name, block in (figures["groups"] or {}).items():
        logger.info(
            f"  {name}: {block['labeled']:,} labeled of {block['size']:,}, "
            f"{block['scored']:,} scored; sentiment {pct(block['sentiment_agreement'])}, "
            f"target {pct(block['target_agreement'])}, joint "
            f"{pct(block['joint_agreement'])}"
        )
    for label, block in (figures["by_class"] or {}).items():
        mix = (figures["class_mix"] or {}).get(label, {})
        logger.info(
            f"  {label}: predicted {block['predicted']:,} / labeled "
            f"{block['labeled']:,}; precision {pct(block['precision'])}, recall "
            f"{pct(block['recall'])}, toward {pct(block['toward_precision'])}; share "
            f"classifier {pct(mix.get('classifier'))} vs manual "
            f"{pct(mix.get('manual'))}, gap {pm(mix.get('gap'), mix.get('gap_margin'))}"
        )
    logger.info(
        f"  needed the thread {pct(figures['context_share'])}, unsure "
        f"{pct(figures['unsure_share'])}, rejected {pct(figures['reject_share'])}"
    )
