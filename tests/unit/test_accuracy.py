"""Tests for pipeline.accuracy (the draw, the workbook round trip, the figures)."""

import json
import logging
from pathlib import Path

import polars as pl
import pytest
from openpyxl import load_workbook

from pipeline.accuracy import (
    CLASSIFIER_SHEET,
    GROUP_FIRST,
    GROUP_HELD_OUT,
    GROUP_ORDERED,
    GROUPS,
    LABEL_COLUMNS,
    LABELS_SHEET,
    LISTS_SHEET,
    META_SHEET,
    REJECT_REASONS,
    SAMPLE_COLUMNS,
    SENTIMENT_VERDICTS,
    TARGET_NONE,
    TARGET_OTHER,
    draw_sample,
    load_accuracy_sample,
    load_passes,
    read_workbook,
    score_sample,
    target_options,
    unlabeled_figures,
    write_workbook,
)
from pipeline.schemas import (
    ACCURACY_SAMPLE_SCHEMA,
    AccuracyFigures,
    ClassAgreement,
    ClassMix,
    GroupFigures,
)
from utils.constants import ACCURACY_CLASS_MIN_N
from utils.player_config import load_player_config_version

_FACT_SCHEMA = pl.Schema(
    {
        "comment_id": pl.String,
        "link_id": pl.String,
        "body": pl.String,
        "mentioned_players": pl.List(pl.String),
        "sentiment": pl.String,
        "confidence": pl.Float64,
        "sentiment_player": pl.String,
        "attributed_player": pl.String,
    }
)

STAMPS = {
    "players_config_version": "4.6",
    "classifier_sentiment_model": "claude-haiku-4-5-20251001",
    "classifier_sentiment_prompt_version": "v2-production+s-hint",
    "sample_seed": "11",
    "sample_n": "3",
    "drawn_at": "2026-09-24",
}


def _fact(rows: list[dict]) -> pl.DataFrame:
    """A fact-shaped frame with stable defaults per row."""
    defaults = {
        "link_id": "t3_post1",
        "body": "a comment",
        "mentioned_players": ["LeBron James"],
        "sentiment": "neg",
        "confidence": 0.95,
        "sentiment_player": "LeBron James",
        "attributed_player": "LeBron James",
    }
    return pl.DataFrame([{**defaults, **row} for row in rows], schema=_FACT_SCHEMA)


def _sample() -> pl.DataFrame:
    """Three drawn rows: a single mention, a double mention, a neutral."""
    return pl.DataFrame(
        {
            "comment_id": ["c1", "c2", "c3"],
            "permalink": [
                "https://www.reddit.com/r/nba/comments/post1/comment/c1/",
                "https://www.reddit.com/r/nba/comments/post1/comment/c2/",
                "https://www.reddit.com/r/nba/comments/post2/comment/c3/",
            ],
            "post_title": ["Game thread", "Game thread", None],
            "body": ["LeBron washed", "Luka > LeBron", "Jokic played"],
            "mentioned_players": [
                ["LeBron James"],
                ["Luka Doncic", "LeBron James"],
                ["Nikola Jokic"],
            ],
            "sentiment": ["neg", "neg", "neu"],
            "confidence": [0.95, 0.9, 0.5],
            "sentiment_player": ["LeBron James", "LeBron James", None],
            "attributed_player": ["LeBron James", "LeBron James", "Nikola Jokic"],
        },
        schema=pl.Schema(
            {
                "comment_id": pl.String,
                "permalink": pl.String,
                "post_title": pl.String,
                "body": pl.String,
                "mentioned_players": pl.List(pl.String),
                "sentiment": pl.String,
                "confidence": pl.Float64,
                "sentiment_player": pl.String,
                "attributed_player": pl.String,
            }
        ),
    )


def _fill(path: Path, verdicts: dict[str, tuple]) -> None:
    """Fill the labels sheet: comment_id -> (sentiment, target, reject, note)."""
    workbook = load_workbook(path)
    sheet = workbook[LABELS_SHEET]
    for row in sheet.iter_rows(min_row=2):
        comment_id = row[0].value
        if comment_id in verdicts:
            for cell, value in zip(row[4:8], verdicts[comment_id]):
                cell.value = value
    workbook.save(path)


COMPLETE = {
    "c1": ("neg", "LeBron James", None, None),
    "c2": ("neg", "Luka Doncic", None, "ctx: the target is Luka"),
    "c3": ("neu", TARGET_NONE, None, None),
}


@pytest.fixture
def workbook(tmp_path) -> Path:
    """The labeling workbook for _sample, written and unfilled."""
    path = tmp_path / "accuracy_sample.xlsx"
    write_workbook(_sample(), path, STAMPS)
    return path


class TestDrawSample:
    """Tests for draw_sample."""

    def _population(self, size: int) -> pl.DataFrame:
        return _fact(
            [
                {"comment_id": f"c{i:02d}", "link_id": f"t3_p{i % 3}"}
                for i in range(size)
            ]
        )

    def test_is_deterministic_under_the_seed(self):
        """The same seed draws the same ids in the same order; another seed differs."""
        population = self._population(40)

        first = draw_sample(population, None, n=10, seed=3)
        second = draw_sample(population, None, n=10, seed=3)
        other = draw_sample(population, None, n=10, seed=4)

        assert first["comment_id"].to_list() == second["comment_id"].to_list()
        assert first["comment_id"].to_list() != other["comment_id"].to_list()
        assert first.columns == list(SAMPLE_COLUMNS)

    def test_rows_come_back_in_random_order(self):
        """A top-down prefix is a random sample only if the draw is shuffled."""
        drawn = draw_sample(self._population(60), None, n=20, seed=3)

        ids = drawn["comment_id"].to_list()
        assert ids != sorted(ids)

    def test_population_is_attributed_rows_with_a_real_label(self):
        """Unattributed and error rows are outside the draw."""
        population = _fact(
            [
                {"comment_id": "keep1"},
                {"comment_id": "keep2", "sentiment": "pos"},
                {"comment_id": "drop1", "attributed_player": None},
                {"comment_id": "drop2", "sentiment": "error"},
            ]
        )

        sample = draw_sample(population, None, n=2, seed=1)

        assert sorted(sample["comment_id"].to_list()) == ["keep1", "keep2"]

    def test_raises_when_the_population_is_short(self):
        """Asking for more rows than the population holds is an error, not a smaller draw."""
        with pytest.raises(ValueError, match="fewer than the 5 requested"):
            draw_sample(self._population(3), None, n=5, seed=1)

    def test_permalink_from_post_and_comment_ids(self):
        """The permalink strips the t3_ prefix and points at the comment."""
        population = _fact([{"comment_id": "abc", "link_id": "t3_xyz"}])

        sample = draw_sample(population, None, n=1, seed=1)

        assert sample["permalink"][0] == (
            "https://www.reddit.com/r/nba/comments/xyz/comment/abc/"
        )

    def test_titles_join_from_the_bridge(self):
        """With a bridge each row carries its post's title; an unbridged post is null."""
        population = _fact(
            [
                {"comment_id": "a", "link_id": "t3_known"},
                {"comment_id": "b", "link_id": "t3_unknown"},
            ]
        )
        posts = pl.DataFrame({"post_id": ["t3_known"], "title": ["Game thread"]})

        sample = draw_sample(population, posts, n=2, seed=1).sort("comment_id")

        assert sample["post_title"].to_list() == ["Game thread", None]

    def test_without_a_bridge_titles_are_null(self):
        """No bridge given: the column exists, every title null."""
        sample = draw_sample(self._population(4), None, n=2, seed=1)

        assert sample["post_title"].dtype == pl.String
        assert sample["post_title"].null_count() == 2

    def test_warns_when_a_predicted_class_is_thin(self, caplog):
        """A class under the floor in the draw is flagged before labeling starts."""
        population = self._population(ACCURACY_CLASS_MIN_N + 5)

        with caplog.at_level(logging.WARNING, logger="pipeline.accuracy"):
            draw_sample(population, None, n=ACCURACY_CLASS_MIN_N, seed=1)

        assert "fall under" in caplog.text
        assert "'neu', 'pos'" in caplog.text


class TestTargetOptions:
    """Tests for target_options."""

    def test_mentions_then_none_then_other(self):
        """The list is the row's mentions in order, then the two escapes."""
        assert target_options(["Luka Doncic", "LeBron James"]) == (
            "Luka Doncic",
            "LeBron James",
            TARGET_NONE,
            TARGET_OTHER,
        )


class TestWriteWorkbook:
    """Tests for write_workbook: what the labeler sees and what they don't."""

    def test_labels_sheet_carries_no_prediction(self, workbook):
        """The visible sheet is the comment plus empty verdict columns."""
        sheet = load_workbook(workbook)[LABELS_SHEET]

        header = [cell.value for cell in sheet[1]]
        rows = [[cell.value for cell in row] for row in sheet.iter_rows(min_row=2)]

        assert header == list(LABEL_COLUMNS)
        assert rows[0][:4] == ["c1", "open", "Game thread", "LeBron washed"]
        assert rows[0][4:] == [None, None, None, None]
        assert sheet["B2"].hyperlink.target == _sample()["permalink"][0]

    def test_classifier_lists_and_meta_sheets_are_hidden(self, workbook):
        """The join keys and the draw's stamps ride along out of sight."""
        book = load_workbook(workbook)

        assert book[LABELS_SHEET].sheet_state == "visible"
        for name in (CLASSIFIER_SHEET, LISTS_SHEET, META_SHEET):
            assert book[name].sheet_state == "hidden"

    def test_verdict_columns_are_list_validated(self, workbook):
        """Sentiment and reject take one list each over the whole column."""
        sheet = load_workbook(workbook)[LABELS_SHEET]
        validations = {
            str(v.sqref): v.formula1 for v in sheet.data_validations.dataValidation
        }

        assert validations["E2:E4"] == '"' + ",".join(SENTIMENT_VERDICTS) + '"'
        assert validations["G2:G4"] == '"' + ",".join(REJECT_REASONS) + '"'

    def test_a_typed_value_outside_the_list_is_refused_in_the_cell(self, workbook):
        """Every dropdown raises a stop alert, so a typo is caught while labeling."""
        sheet = load_workbook(workbook)[LABELS_SHEET]

        for validation in sheet.data_validations.dataValidation:
            assert validation.showErrorMessage is True
            assert validation.errorStyle == "stop"
            assert validation.allow_blank is True

    def test_target_list_is_per_row(self, workbook):
        """Each row's target dropdown is its own mentions plus none and other."""
        book = load_workbook(workbook)
        lists = [
            [cell.value for cell in row if cell.value is not None]
            for row in book[LISTS_SHEET].iter_rows()
        ]
        by_cell = {}
        for validation in book[LABELS_SHEET].data_validations.dataValidation:
            for cell_range in str(validation.sqref).split():
                by_cell[cell_range] = validation.formula1

        assert lists == [
            ["LeBron James", TARGET_NONE, TARGET_OTHER],
            ["Luka Doncic", "LeBron James", TARGET_NONE, TARGET_OTHER],
            ["Nikola Jokic", TARGET_NONE, TARGET_OTHER],
        ]
        assert by_cell["F2"] == f"{LISTS_SHEET}!$A$1:$C$1"
        assert by_cell["F3"] == f"{LISTS_SHEET}!$A$2:$D$2"
        assert by_cell["F4"] == f"{LISTS_SHEET}!$A$3:$C$3"

    def test_rows_sharing_a_list_share_a_validation(self, tmp_path):
        """Distinct lists, not rows, drive the lists sheet."""
        path = tmp_path / "book.xlsx"
        sample = pl.concat(
            [
                _sample(),
                _sample().with_columns(pl.col("comment_id").str.replace("c", "d")),
            ]
        )

        write_workbook(sample, path, STAMPS)

        book = load_workbook(path)
        assert book[LISTS_SHEET].max_row == 3
        assert len(book[LABELS_SHEET].data_validations.dataValidation) == 5


class TestLoadPasses:
    """Tests for load_passes."""

    def test_absent_file_is_none(self, tmp_path):
        """No passes file: the caller treats the whole draw as the ordered group."""
        assert load_passes(tmp_path / "missing.json") is None

    def test_reads_both_lists_and_tolerates_a_missing_key(self, tmp_path):
        """Each list is read as strings; a missing key is an empty list."""
        path = tmp_path / "passes.json"
        path.write_text(json.dumps({"first": ["c3"]}))

        assert load_passes(path) == {GROUP_FIRST: ["c3"], GROUP_HELD_OUT: []}

    def test_an_id_in_both_lists_is_refused(self, tmp_path):
        """A row is in one group."""
        path = tmp_path / "passes.json"
        path.write_text(json.dumps({"first": ["c1"], "held_out": ["c1"]}))

        with pytest.raises(ValueError, match="both first and held_out"):
            load_passes(path)


class TestReadWorkbook:
    """Tests for read_workbook: the round trip, the groups and every refusal."""

    def test_round_trip(self, workbook):
        """A complete workbook comes back as every drawn row in draw order, with stamps."""
        _fill(workbook, COMPLETE)

        sample, stamps = read_workbook(workbook)

        assert sample.schema == ACCURACY_SAMPLE_SCHEMA
        assert sample["comment_id"].to_list() == ["c1", "c2", "c3"]
        assert sample["group"].to_list() == [GROUP_ORDERED] * 3
        assert sample["position"].to_list() == [0, 1, 2]
        assert sample["mention_count"].to_list() == [1, 2, 1]
        assert sample["labeled"].to_list() == [True, True, True]
        assert sample["label_sentiment"].to_list() == ["neg", "neg", "neu"]
        assert sample["label_target"].to_list() == [
            "LeBron James",
            "Luka Doncic",
            TARGET_NONE,
        ]
        assert sample["needed_context"].to_list() == [False, True, False]
        assert sample["unsure"].to_list() == [False, False, False]
        assert sample["note"].to_list() == [None, "ctx: the target is Luka", None]
        assert sample["sentiment"].to_list() == ["neg", "neg", "neu"]
        assert sample["sentiment_player"].to_list() == [
            "LeBron James",
            "LeBron James",
            None,
        ]
        assert sample["attributed_player"][2] == "Nikola Jokic"
        assert sample["confidence"].to_list() == [0.95, 0.9, 0.5]
        assert stamps == STAMPS

    def test_rejected_row_carries_the_reason_and_no_labels(self, workbook):
        """A reject needs no verdicts; whatever was typed beside it is dropped."""
        _fill(
            workbook,
            {**COMPLETE, "c2": ("pos", "other", "alias_false_positive", "a referee")},
        )

        sample, _ = read_workbook(workbook)

        assert sample.row(1, named=True) == {
            "comment_id": "c2",
            "group": GROUP_ORDERED,
            "position": 1,
            "mention_count": 2,
            "sentiment": "neg",
            "confidence": 0.9,
            "sentiment_player": "LeBron James",
            "attributed_player": "LeBron James",
            "labeled": True,
            "label_sentiment": None,
            "label_target": None,
            "reject": "alias_false_positive",
            "needed_context": False,
            "unsure": False,
            "note": "a referee",
        }

    def test_unlabeled_rows_come_back_unlabeled(self, workbook):
        """A partly filled workbook reads; the tail is labeled=False with null labels."""
        _fill(workbook, {"c1": COMPLETE["c1"]})

        sample, _ = read_workbook(workbook)

        assert sample["labeled"].to_list() == [True, False, False]
        assert sample["label_sentiment"].to_list() == ["neg", None, None]
        assert sample["needed_context"].to_list() == [False, False, False]

    def test_unsure_tag_is_read_from_the_note(self, workbook):
        """A question mark anywhere in the note marks the row unsure."""
        _fill(workbook, {"c1": ("neg", "LeBron James", None, "? could be neu")})

        sample, _ = read_workbook(workbook)

        assert sample["unsure"][0] is True

    def test_groups_follow_the_passes(self, workbook):
        """Ids in the passes file take their group; the rest are ordered."""
        _fill(workbook, COMPLETE)

        sample, _ = read_workbook(
            workbook, {GROUP_FIRST: ["c3"], GROUP_HELD_OUT: ["c2"]}
        )

        assert sample["group"].to_list() == [GROUP_ORDERED, GROUP_HELD_OUT, GROUP_FIRST]

    def test_a_passes_id_outside_the_draw_is_refused(self, workbook):
        """The passes file must describe this draw."""
        with pytest.raises(ValueError, match="first id zz is not in the draw"):
            read_workbook(workbook, {GROUP_FIRST: ["zz"], GROUP_HELD_OUT: []})

    def test_a_skipped_ordered_row_is_refused(self, workbook):
        """The ordered group is a prefix sample: a gap above a labeled row is named."""
        _fill(workbook, {"c2": COMPLETE["c2"], "c3": COMPLETE["c3"]})

        with pytest.raises(
            ValueError, match=r"1 ordered row\(s\) were skipped.*rows 2"
        ):
            read_workbook(workbook)

    def test_a_gap_in_another_group_is_not_a_skip(self, workbook):
        """Only the ordered group has to be labeled top-down."""
        _fill(workbook, {"c2": COMPLETE["c2"]})

        sample, _ = read_workbook(workbook, {GROUP_FIRST: ["c1"], GROUP_HELD_OUT: []})

        assert sample["labeled"].to_list() == [False, True, False]

    def test_sorted_rows_still_read(self, workbook):
        """The join is by comment id, so a sorted sheet is fine."""
        _fill(workbook, COMPLETE)
        book = load_workbook(workbook)
        sheet = book[LABELS_SHEET]
        rows = [[cell.value for cell in row] for row in sheet.iter_rows(min_row=2)]
        for index, row in enumerate(reversed(rows), start=2):
            for column, value in enumerate(row, start=1):
                sheet.cell(row=index, column=column, value=value)
        book.save(workbook)

        sample, _ = read_workbook(workbook)

        assert sample["comment_id"].to_list() == ["c1", "c2", "c3"]

    def test_trailing_empty_rows_and_columns_are_ignored(self, workbook):
        """A stray blank row under the table or an empty ninth column is not a problem."""
        _fill(workbook, COMPLETE)
        book = load_workbook(workbook)
        book[LABELS_SHEET].cell(row=6, column=8, value=None)
        book[LABELS_SHEET].cell(row=1, column=9, value=None)
        book[LABELS_SHEET].cell(row=2, column=9, value="x")
        book.save(workbook)

        sample, _ = read_workbook(workbook)

        assert sample.height == 3

    @pytest.mark.parametrize(
        "verdicts,match",
        [
            ({"c1": (None, "LeBron James", None, None)}, r"row 2: sentiment None"),
            (
                {"c1": ("positive", "LeBron James", None, None)},
                r"row 2: sentiment 'positive'",
            ),
            ({"c1": ("neg", None, None, None)}, r"row 2: target None is not one of"),
            (
                {"c2": ("neg", "Nikola Jokic", None, None)},
                r"row 3: target 'Nikola Jokic'",
            ),
            ({"c3": (None, None, "spam", None)}, r"row 4: reject 'spam'"),
        ],
        ids=[
            "blank-sentiment",
            "off-list-sentiment",
            "blank-target",
            "off-row-target",
            "unknown-reject",
        ],
    )
    def test_refuses_an_off_list_verdict_naming_the_row(
        self, workbook, verdicts, match
    ):
        """Every verdict must come from its list; the message names the row."""
        _fill(workbook, {**COMPLETE, **verdicts})

        with pytest.raises(ValueError, match=match):
            read_workbook(workbook)

    def test_refuses_a_missing_row(self, workbook):
        """Every drawn id must be on the sheet; a deleted row is named."""
        _fill(workbook, COMPLETE)
        book = load_workbook(workbook)
        book[LABELS_SHEET].delete_rows(3)
        book.save(workbook)

        with pytest.raises(ValueError, match=r"1 drawn row\(s\) are absent.*c2"):
            read_workbook(workbook)

    def test_refuses_a_duplicate_and_an_unknown_id(self, workbook):
        """A copied row and a row outside the draw are both named."""
        _fill(workbook, COMPLETE)
        book = load_workbook(workbook)
        sheet = book[LABELS_SHEET]
        sheet.append(["c1", None, None, None, "neg", "LeBron James", None, None])
        sheet.append(["zz", None, None, None, "neg", TARGET_NONE, None, None])
        book.save(workbook)

        with pytest.raises(ValueError) as excinfo:
            read_workbook(workbook)

        assert "row 5: c1 appears twice" in str(excinfo.value)
        assert "row 6: zz is not in the draw" in str(excinfo.value)

    def test_reports_every_problem_at_once(self, workbook):
        """One pass names all the rows, so the fix is one edit session."""
        _fill(
            workbook,
            {
                "c1": ("neg", None, None, None),
                "c2": ("positive", "Luka Doncic", None, None),
            },
        )

        with pytest.raises(ValueError) as excinfo:
            read_workbook(workbook)

        assert "2 problem(s)" in str(excinfo.value)
        assert "row 2: target None" in str(excinfo.value)
        assert "row 3: sentiment 'positive'" in str(excinfo.value)

    def test_refuses_a_changed_header(self, workbook):
        """The columns are the contract; a renamed header is not read around."""
        book = load_workbook(workbook)
        book[LABELS_SHEET]["E1"] = "Sentiment"
        book.save(workbook)

        with pytest.raises(ValueError, match="header was changed"):
            read_workbook(workbook)

    def test_refuses_a_missing_sheet(self, workbook):
        """Without the hidden join sheets the labels cannot be scored."""
        book = load_workbook(workbook)
        del book[CLASSIFIER_SHEET]
        book.save(workbook)

        with pytest.raises(ValueError, match="sheet 'classifier' is missing"):
            read_workbook(workbook)


def _labeled(rows: list[dict]) -> pl.DataFrame:
    """A sample frame with per-row defaults: one ordered, labeled LeBron row,
    predicted negative, labeled negative toward him."""
    defaults = {
        "group": GROUP_ORDERED,
        "mention_count": 1,
        "sentiment": "neg",
        "confidence": 0.9,
        "sentiment_player": "LeBron James",
        "attributed_player": "LeBron James",
        "labeled": True,
        "label_sentiment": "neg",
        "label_target": "LeBron James",
        "reject": None,
        "needed_context": False,
        "unsure": False,
        "note": None,
    }
    return pl.DataFrame(
        [
            {"comment_id": f"c{i}", "position": i, **defaults, **row}
            for i, row in enumerate(rows)
        ],
        schema=ACCURACY_SAMPLE_SCHEMA,
    )


UNLABELED = {"labeled": False, "label_sentiment": None, "label_target": None}
REJECTED = {
    "label_sentiment": None,
    "label_target": None,
    "reject": "alias_false_positive",
}

# Two groups: four first-pass rows (one reject), six skipped rows of which
# three are labeled in order, one is held out and two are untouched.
TWO_GROUPS = _labeled(
    [
        {"group": GROUP_FIRST},  # 0: neg right, toward right
        {"group": GROUP_FIRST, "label_sentiment": "neu", "needed_context": True},  # 1
        {"group": GROUP_FIRST, "sentiment": "pos", "label_sentiment": "pos"},  # 2
        {"group": GROUP_FIRST, **REJECTED},  # 3
        {"sentiment": "neu", "label_sentiment": "neu"},  # 4: right
        {"sentiment": "pos", "label_sentiment": "neg", "unsure": True},  # 5: wrong
        {"label_target": TARGET_NONE},  # 6: neg right, toward wrong
        UNLABELED,  # 7
        {"group": GROUP_HELD_OUT, "sentiment": "pos", "label_sentiment": "pos"},  # 8
        UNLABELED,  # 9
    ]
)


class TestScoreSample:
    """Tests for score_sample."""

    def test_unlabeled_sample_is_the_unlabeled_block(self):
        """No verdict anywhere: nothing is claimed."""
        figures = score_sample(_labeled([UNLABELED, UNLABELED]), seed=1, drawn_at=None)

        assert figures == unlabeled_figures()

    def test_counts_and_identity(self):
        """Drawn counts the draw, scored and rejected the estimating groups."""
        figures = score_sample(TWO_GROUPS, seed=11, drawn_at="2026-09-24", rubric="v1")

        assert figures["labeled"] is True
        assert (figures["drawn"], figures["scored"], figures["rejected"]) == (10, 6, 1)
        assert (figures["seed"], figures["drawn_at"], figures["rubric"]) == (
            11,
            "2026-09-24",
            "v1",
        )

    def test_a_held_out_reject_is_not_counted(self):
        """Scored and rejected describe the same rows: the two estimating groups."""
        sample = _labeled([{}, {"group": GROUP_HELD_OUT, **REJECTED}, REJECTED])

        figures = score_sample(sample, seed=1, drawn_at=None)

        assert (figures["drawn"], figures["scored"], figures["rejected"]) == (3, 1, 1)

    def test_groups_are_reported_unweighted(self):
        """Each group's own figures, the held-out rows included, for the record."""
        groups = score_sample(TWO_GROUPS, seed=1, drawn_at=None)["groups"]

        assert groups[GROUP_FIRST] == {
            "size": 4,
            "weight": 0.4,
            "labeled": 4,
            "rejected": 1,
            "scored": 3,
            "sentiment_agreement": 0.6667,
            "target_agreement": 1.0,
            "joint_agreement": 0.6667,
        }
        assert groups[GROUP_ORDERED] == {
            "size": 5,
            "weight": 0.6,
            "labeled": 3,
            "rejected": 0,
            "scored": 3,
            "sentiment_agreement": 0.6667,
            "target_agreement": 0.5,
            "joint_agreement": 0.3333,
        }
        assert groups[GROUP_HELD_OUT]["size"] == 1
        assert groups[GROUP_HELD_OUT]["sentiment_agreement"] == 1.0

    def test_sizes_sum_to_the_draw_and_the_ordered_weight_carries_the_held_out(self):
        """A group's size is its own rows; the held-out rows' weight rides with
        the ordered group, so the weights sum to one."""
        figures = score_sample(TWO_GROUPS, seed=1, drawn_at=None)
        groups = figures["groups"]

        assert sum(block["size"] for block in groups.values()) == figures["drawn"]
        assert [groups[name]["weight"] for name in GROUPS] == [0.4, 0.6, 0.0]

    def test_headline_weights_the_groups_by_size(self):
        """First pass at 4/10, ordered at 6/10; the held-out row never estimates."""
        figures = score_sample(TWO_GROUPS, seed=1, drawn_at=None)

        assert figures["sentiment_agreement"] == 0.6667
        assert figures["target_agreement"] == 0.7
        assert figures["joint_agreement"] == 0.4667

    def test_margins_carry_the_draw_and_the_ordered_sampling(self):
        """Two-phase variance: the draw's own term plus the ordered group's, corrected."""
        figures = score_sample(TWO_GROUPS, seed=1, drawn_at=None)

        assert figures["sentiment_margin"] == 0.3696
        assert figures["target_margin"] == 0.4088
        assert figures["joint_margin"] > 0

    def test_per_class_figures_are_weighted_ratios(self):
        """Precision and recall are ratios of weighted shares, counts are raw."""
        by_class = score_sample(TWO_GROUPS, seed=1, drawn_at=None)["by_class"]

        assert by_class["neg"] == {
            "predicted": 3,
            "labeled": 3,
            "precision": 0.7143,
            "recall": 0.625,
            "toward_precision": 0.2857,
        }
        assert by_class["pos"] == {
            "predicted": 2,
            "labeled": 1,
            "precision": 0.4,
            "recall": 1.0,
            "toward_precision": 0.4,
        }
        assert by_class["neu"]["precision"] == 1.0
        assert by_class["neu"]["recall"] == 0.6

    def test_class_mix_and_shares(self):
        """What each side's rate would read, and the tagged shares, weighted."""
        figures = score_sample(TWO_GROUPS, seed=1, drawn_at=None)

        assert figures["class_mix"]["neg"] == {"classifier": 0.4667, "manual": 0.5333}
        assert figures["context_share"] == 0.1333
        assert figures["unsure_share"] == 0.2
        assert figures["reject_share"] == 0.1

    def test_two_name_row_judged_for_another_player_is_not_compared_on_sentiment(self):
        """A manual target that is a different listed player makes the sentiment
        incomparable; the row still counts against the target and the joint."""
        sample = _labeled(
            [
                {
                    "mention_count": 2,
                    "label_sentiment": "pos",
                    "label_target": "Luka Doncic",
                },
                {},
            ]
        )

        figures = score_sample(sample, seed=1, drawn_at=None)

        assert figures["sentiment_agreement"] == 1.0
        assert figures["target_agreement"] == 0.5
        assert figures["joint_agreement"] == 0.5

    def test_a_single_group_reads_as_a_plain_sample(self):
        """Without a first pass the ordered group carries the whole weight."""
        sample = _labeled([{}, {"label_sentiment": "neu"}, UNLABELED, UNLABELED])

        figures = score_sample(sample, seed=1, drawn_at=None)

        assert figures["groups"].keys() == {GROUP_ORDERED}
        assert figures["sentiment_agreement"] == 0.5
        assert figures["sentiment_margin"] > 0

    def test_blocks_match_the_contract(self):
        """Every block carries exactly the contract's fields, in order."""
        figures = score_sample(TWO_GROUPS, seed=1, drawn_at=None)

        assert list(figures) == list(AccuracyFigures.__annotations__)
        assert list(unlabeled_figures()) == list(AccuracyFigures.__annotations__)
        assert list(figures["groups"][GROUP_FIRST]) == list(
            GroupFigures.__annotations__
        )
        assert list(figures["by_class"]["neg"]) == list(ClassAgreement.__annotations__)
        assert list(figures["class_mix"]["neg"]) == list(ClassMix.__annotations__)


class TestLoadAccuracySample:
    """Tests for load_accuracy_sample: the file on disk, or none."""

    FACT_STAMPS = {
        "classifier_sentiment_model": "claude-haiku-4-5-20251001",
        "classifier_sentiment_prompt_version": "v2-production+s-hint",
    }

    def _write(
        self, path: Path, sample: pl.DataFrame = TWO_GROUPS, **overrides
    ) -> Path:
        metadata = {
            "players_config_version": load_player_config_version(),
            **self.FACT_STAMPS,
            "sample_seed": "11",
            "drawn_at": "2026-09-24",
            "rubric_version": "v1",
            **overrides,
        }
        sample.write_parquet(
            path, metadata={k: v for k, v in metadata.items() if v is not None}
        )
        return path

    def test_absent_file_is_unlabeled(self, tmp_path, caplog):
        """No file: the unlabeled block, and a warning that says so."""
        with caplog.at_level(logging.WARNING, logger="pipeline.accuracy"):
            figures = load_accuracy_sample(
                tmp_path / "missing.parquet", self.FACT_STAMPS
            )

        assert figures == unlabeled_figures()
        assert "no accuracy figure" in caplog.text

    def test_none_path_is_unlabeled(self):
        """No path at all reads the same as a missing file."""
        assert load_accuracy_sample(None, self.FACT_STAMPS) == unlabeled_figures()

    def test_file_without_a_verdict_is_unlabeled(self, tmp_path, caplog):
        """An imported but unfilled workbook claims nothing."""
        path = self._write(tmp_path / "s.parquet", _labeled([UNLABELED, UNLABELED]))

        with caplog.at_level(logging.WARNING, logger="pipeline.accuracy"):
            figures = load_accuracy_sample(path, self.FACT_STAMPS)

        assert figures == unlabeled_figures()
        assert "holds no verdict" in caplog.text

    def test_scores_the_file_with_its_stamps(self, tmp_path, caplog):
        """The figures come from the file, seed, date and rubric from its metadata."""
        path = self._write(tmp_path / "accuracy_sample.parquet")

        with caplog.at_level(logging.WARNING, logger="pipeline.accuracy"):
            figures = load_accuracy_sample(path, self.FACT_STAMPS)

        assert figures["labeled"] is True
        assert figures["scored"] == 6
        assert (figures["seed"], figures["drawn_at"], figures["rubric"]) == (
            11,
            "2026-09-24",
            "v1",
        )
        assert caplog.text == ""

    def test_classifier_mismatch_warns(self, tmp_path, caplog):
        """A sample labeled against another classifier is scored, but said so."""
        path = self._write(
            tmp_path / "accuracy_sample.parquet",
            classifier_sentiment_prompt_version="v1",
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.accuracy"):
            figures = load_accuracy_sample(path, self.FACT_STAMPS)

        assert figures["labeled"] is True
        assert "describes the classifier it was labeled against" in caplog.text
        assert "'v1'" in caplog.text

    def test_config_drift_warns(self, tmp_path, caplog):
        """The players-config stamp is drift-checked like any config-derived file."""
        path = self._write(
            tmp_path / "accuracy_sample.parquet", players_config_version="0.1"
        )

        with caplog.at_level(logging.WARNING, logger="pipeline.accuracy"):
            load_accuracy_sample(path, self.FACT_STAMPS)

        assert "players_config_version drift" in caplog.text

    def test_wrong_shape_raises(self, tmp_path):
        """A parquet that is not the sample is refused, not scored."""
        path = tmp_path / "accuracy_sample.parquet"
        pl.DataFrame({"comment_id": ["c1"]}).write_parquet(path)

        with pytest.raises(ValueError):
            load_accuracy_sample(path, self.FACT_STAMPS)
