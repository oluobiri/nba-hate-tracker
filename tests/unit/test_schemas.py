"""Tests for pipeline/schemas.py schema validation."""

import json

import polars as pl
import pytest

from pipeline.schemas import (
    AGGREGATE_VIEW_SCHEMAS,
    COMMENT_INPUT_SCHEMA,
    COMMENT_SAMPLES_SCHEMA,
    CORPUS_DAILY_SCHEMA,
    CORPUS_STAGES,
    DASHBOARD_OUTPUT_SCHEMAS,
    METRIC_FORMULAS,
    POPULATIONS,
    TABLE_POPULATIONS,
    Corpus,
    Manifest,
    GAME_SENTIMENT_SCHEMA,
    GAMES_SCHEMA,
    PLAYER_GAME_LOG_SCHEMA,
    PLAYER_GAMES_SCHEMA,
    PLAYER_OVERALL_SCHEMA,
    PLAYERS_CONFIG_COLUMNS,
    PLAYERS_SCHEMA,
    PLAYERS_SNAPSHOT_COLUMNS,
    POSTS_SCHEMA,
    ROSTERS_SCHEMA,
    SENTIMENT_SCHEMA,
    TEAM_GAME_LOG_SCHEMA,
    TEAMS_SCHEMA,
    load_manifest,
    validate_schema,
)
from utils.season_config import CORPUS_KEYS


@pytest.fixture
def sentiment_frame() -> pl.DataFrame:
    """One-row DataFrame conforming exactly to SENTIMENT_SCHEMA."""
    return pl.DataFrame(
        [
            {
                "comment_id": "abc123",
                "body": "LeBron is washed",
                "author": "user123",
                "author_flair_text": "Lakers",
                "author_flair_css_class": "lakers",
                "created_utc": 1709251200,
                "score": 10,
                "link_id": "t3_post123",
                "mentioned_players": ["LeBron James"],
                "sentiment": "neg",
                "confidence": 0.95,
                "sentiment_player": "LeBron James",
                "attributed_player": "LeBron James",
                "fan_team": "Los Angeles Lakers",
                "input_tokens": 100,
                "output_tokens": 20,
            }
        ],
        schema=SENTIMENT_SCHEMA,
    )


class TestLinkIdContract:
    """Contract guards for link_id, the v3 game-thread bridge field (#43)."""

    def test_sentiment_schema_pins_link_id_as_string(self):
        """Verify link_id is part of the sentiment.parquet contract."""
        assert SENTIMENT_SCHEMA["link_id"] == pl.String

    def test_comment_input_schema_reads_link_id(self):
        """Verify the filtered-NDJSON projection carries link_id."""
        assert COMMENT_INPUT_SCHEMA["link_id"] == pl.String


@pytest.fixture
def roster_frame(lebron_roster_row) -> pl.DataFrame:
    """One-row DataFrame conforming exactly to ROSTERS_SCHEMA."""
    return pl.DataFrame([lebron_roster_row], schema=ROSTERS_SCHEMA)


class TestPlayersContract:
    """Contract guards for the Player dimension (players.parquet)."""

    def test_roster_team_is_role_marked(self):
        """Verify the roster column is role-marked from birth — never bare `team`."""
        assert PLAYERS_SCHEMA["roster_team"] == pl.String
        assert "team" not in PLAYERS_SCHEMA.names()

    def test_slug_follows_the_display_key_and_is_not_config(self):
        """Verify the URL slug sits right after attributed_player, derived
        at build rather than curated in players.yaml."""
        assert PLAYERS_SCHEMA.names()[:2] == ["attributed_player", "slug"]
        assert PLAYERS_SCHEMA["slug"] == pl.String
        assert "slug" not in PLAYERS_CONFIG_COLUMNS

    def test_excludes_rejected_columns(self):
        """Verify decided-out columns stay out (logo_url, age, snapshot team fields)."""
        for col in ("logo_url", "age", "player_name", "team_name", "team_abbr"):
            assert col not in PLAYERS_SCHEMA.names()

    def test_snapshot_side_dtypes_derive_from_rosters(self):
        """Verify snapshot-side dtypes match ROSTERS_SCHEMA exactly (no drift)."""
        for col in PLAYERS_SNAPSHOT_COLUMNS:
            assert PLAYERS_SCHEMA[col] == ROSTERS_SCHEMA[col]

    def test_dashboard_outputs_superset(self):
        """Verify the output mapping is the rollups + the dimensions + the
        comment-samples fact subset, and the rollup mapping stays rollup-only."""
        assert set(DASHBOARD_OUTPUT_SCHEMAS) == set(AGGREGATE_VIEW_SCHEMAS) | {
            "players",
            "teams",
            "games",
            "player_games",
            "posts",
            "comment_samples",
            "corpus_daily",
        }
        assert DASHBOARD_OUTPUT_SCHEMAS["players"] is PLAYERS_SCHEMA
        assert "players" not in AGGREGATE_VIEW_SCHEMAS

    def test_player_id_follows_the_display_key(self):
        """Verify every player-keyed output carries the dimension's stable id
        right after attributed_player, typed like the dimension's."""
        player_keyed = {
            name: schema
            for name, schema in DASHBOARD_OUTPUT_SCHEMAS.items()
            if "attributed_player" in schema.names() and name != "players"
        }
        assert set(player_keyed) == {
            "player_overall",
            "player_temporal",
            "player_fan_team",
            "game_sentiment",
            "player_games",
            "comment_samples",
        }
        for name, schema in player_keyed.items():
            at = schema.names().index("attributed_player")
            assert schema.names()[at + 1] == "player_id", name
            assert schema["player_id"] == PLAYERS_SCHEMA["player_id"], name

    def test_no_unmarked_team_outside_the_dimension(self):
        """Verify every Team FK on a produced table carries its role
        (fan_team / roster_team / home_team / away_team); bare `team` is
        the Team dimension's own PK and nothing else."""
        for name, schema in DASHBOARD_OUTPUT_SCHEMAS.items():
            if name == "teams":
                assert "team" in schema.names()
            else:
                assert "team" not in schema.names(), name


class TestTeamsContract:
    """Contract guards for the Team dimension (teams.parquet)."""

    def test_pins_column_set_and_dtypes(self):
        """Verify the spec §3 column set with pinned dtypes."""
        assert TEAMS_SCHEMA == pl.Schema(
            {
                "team": pl.String,
                "abbreviation": pl.String,
                "conference": pl.String,
                "team_id": pl.Int64,
                "logo_url": pl.String,
            }
        )

    def test_pk_is_unmarked_team(self):
        """Verify the dimension's own key is bare `team` — role-marking
        (roster_team/fan_team) applies to FK columns on fact tables."""
        assert TEAMS_SCHEMA.names()[0] == "team"
        assert "fan_team" not in TEAMS_SCHEMA.names()

    def test_joins_outputs_but_not_views(self):
        """Verify teams ships via DASHBOARD_OUTPUT_SCHEMAS only — a
        dimension, not a fact rollup; the views mapping stays fact-only."""
        assert DASHBOARD_OUTPUT_SCHEMAS["teams"] is TEAMS_SCHEMA
        assert "teams" not in AGGREGATE_VIEW_SCHEMAS


class TestGamesContract:
    """Contract guards for the Game dimension (games.parquet)."""

    def test_pins_column_set_and_dtypes(self):
        """Verify the decided column set with pinned dtypes, in order."""
        assert GAMES_SCHEMA == pl.Schema(
            {
                "game_id": pl.String,
                "game_date": pl.Date,
                "season_type": pl.String,
                "nba_cup_final": pl.Boolean,
                "neutral_site": pl.Boolean,
                "home_team": pl.String,
                "away_team": pl.String,
                "home_score": pl.Int64,
                "away_score": pl.Int64,
                "winner": pl.String,
                "playoff_round": pl.Int64,
                "playoff_series": pl.Int64,
                "playoff_game": pl.Int64,
            }
        )

    def test_team_fks_are_role_marked(self):
        """Verify the two Team roles are marked by name — no unmarked
        `team` column, and no abbreviation-typed FK beside the key."""
        assert {"home_team", "away_team"} <= set(GAMES_SCHEMA.names())
        assert "team" not in GAMES_SCHEMA.names()
        assert "abbreviation" not in GAMES_SCHEMA.names()

    def test_joins_outputs_but_not_views(self):
        """Verify games ships via DASHBOARD_OUTPUT_SCHEMAS only — a
        dimension, not a fact rollup."""
        assert DASHBOARD_OUTPUT_SCHEMAS["games"] is GAMES_SCHEMA
        assert "games" not in AGGREGATE_VIEW_SCHEMAS


class TestPlayerGamesContract:
    """Contract guards for the per-player box-score lines (player_games.parquet)."""

    def test_key_columns_lead(self):
        """Verify the PK is (game_id, attributed_player): the player key
        carries the dimension's name so the client join to game_sentiment
        is on identical column names."""
        assert PLAYER_GAMES_SCHEMA.names()[:2] == ["game_id", "attributed_player"]
        assert PLAYER_GAMES_SCHEMA["player_id"] == pl.Int64

    def test_box_score_dtypes_derive_from_snapshot(self):
        """Verify every box-score column keeps the snapshot's dtype."""
        for col in ("minutes", "pts", "reb", "ast", "plus_minus"):
            assert PLAYER_GAMES_SCHEMA[col] == PLAYER_GAME_LOG_SCHEMA[col]
            assert PLAYER_GAMES_SCHEMA[col] == TEAM_GAME_LOG_SCHEMA[col]

    def test_roster_team_is_the_dated_roster_role(self):
        """Verify the line carries `roster_team` and `opponent` as canonical
        Team FKs plus is_home — never a snapshot abbreviation column."""
        for col in ("roster_team", "opponent", "is_home"):
            assert col in PLAYER_GAMES_SCHEMA.names()
        assert "team_abbr" not in PLAYER_GAMES_SCHEMA.names()

    def test_joins_outputs_but_not_views(self):
        """Verify player_games ships via DASHBOARD_OUTPUT_SCHEMAS only."""
        assert DASHBOARD_OUTPUT_SCHEMAS["player_games"] is PLAYER_GAMES_SCHEMA
        assert "player_games" not in AGGREGATE_VIEW_SCHEMAS


class TestPostsContract:
    """Contract guards for the Post bridge (posts.parquet / posts_bridge.parquet)."""

    def test_key_is_the_fact_link_id(self):
        """Verify post_id leads and is typed like sentiment.link_id, the
        join it exists for."""
        assert POSTS_SCHEMA.names()[0] == "post_id"
        assert POSTS_SCHEMA["post_id"] == SENTIMENT_SCHEMA["link_id"]

    def test_bridge_columns(self):
        """Verify the derived trio: type, nullable game FK, primary flag."""
        assert POSTS_SCHEMA["post_type"] == pl.String
        assert POSTS_SCHEMA["game_id"] == GAMES_SCHEMA["game_id"]
        assert POSTS_SCHEMA["is_primary"] == pl.Boolean
        assert "fan_team" not in POSTS_SCHEMA.names()

    def test_joins_outputs_but_not_views(self):
        """Verify posts ships via DASHBOARD_OUTPUT_SCHEMAS only — a bridge,
        not a fact rollup."""
        assert DASHBOARD_OUTPUT_SCHEMAS["posts"] is POSTS_SCHEMA
        assert "posts" not in AGGREGATE_VIEW_SCHEMAS


class TestGameSentimentContract:
    """Contract guards for the Player x Game rollup (game_sentiment.parquet)."""

    def test_keys_lead_and_match_the_dimensions(self):
        """Verify the two FKs lead, typed like the dimension keys they point at
        and named like player_games' so the client-side join is USING."""
        assert GAME_SENTIMENT_SCHEMA.names()[:3] == [
            "attributed_player",
            "player_id",
            "game_id",
        ]
        assert (
            GAME_SENTIMENT_SCHEMA["attributed_player"]
            == PLAYERS_SCHEMA["attributed_player"]
        )
        assert GAME_SENTIMENT_SCHEMA["game_id"] == GAMES_SCHEMA["game_id"]
        assert set(PLAYER_GAMES_SCHEMA.names()[:3]) == set(
            GAME_SENTIMENT_SCHEMA.names()[:3]
        )

    def test_metrics_match_the_other_views(self):
        """Verify the measure block is the shared compute_metrics shape, then
        the room-size count last."""
        metrics = PLAYER_OVERALL_SCHEMA.names()[2:]
        assert GAME_SENTIMENT_SCHEMA.names()[3:] == [*metrics, "thread_comment_count"]
        for col in metrics:
            assert GAME_SENTIMENT_SCHEMA[col] == PLAYER_OVERALL_SCHEMA[col]
        assert GAME_SENTIMENT_SCHEMA["thread_comment_count"] == pl.Int64

    def test_excludes_rejected_columns(self):
        """Verify decided-out columns stay out: no verdict label, no baseline,
        no pre-joined box score, no whole-room size (that is posts')."""
        for col in (
            "verdict",
            "baseline",
            "delta",
            "pts",
            "plus_minus",
            "num_comments",
        ):
            assert col not in GAME_SENTIMENT_SCHEMA.names()

    def test_is_a_view(self):
        """Verify game_sentiment is a fact rollup: in AGGREGATE_VIEW_SCHEMAS,
        hence in the outputs."""
        assert AGGREGATE_VIEW_SCHEMAS["game_sentiment"] is GAME_SENTIMENT_SCHEMA
        assert DASHBOARD_OUTPUT_SCHEMAS["game_sentiment"] is GAME_SENTIMENT_SCHEMA


class TestGameLogSnapshotsContract:
    """Contract guards for the game-log reference assets."""

    def test_team_log_grain_columns(self):
        """Verify the team log keys on game x team and keeps the raw matchup."""
        for col in ("season_type", "game_id", "team_id", "team_abbr", "matchup"):
            assert col in TEAM_GAME_LOG_SCHEMA.names()
        assert TEAM_GAME_LOG_SCHEMA["game_date"] == pl.Date

    def test_player_log_grain_columns(self):
        """Verify the player log keys on game x player, all players."""
        for col in ("season_type", "game_id", "player_id", "team_abbr", "matchup"):
            assert col in PLAYER_GAME_LOG_SCHEMA.names()
        assert PLAYER_GAME_LOG_SCHEMA["player_id"] == ROSTERS_SCHEMA["player_id"]


class TestCommentSamplesContract:
    """Contract guards for the comment-samples fact subset (comment_samples.parquet)."""

    def test_pins_column_set_and_dtypes(self):
        """Verify the decided column set with pinned dtypes, in order."""
        assert COMMENT_SAMPLES_SCHEMA == pl.Schema(
            {
                "attributed_player": pl.String,
                "player_id": pl.Int64,
                "sentiment": pl.String,
                "rank": pl.Int64,
                "comment_id": pl.String,
                "link_id": pl.String,
                "body": pl.String,
                "score": pl.Int64,
                "created_utc": pl.Int64,
                "fan_team": pl.String,
            }
        )

    def test_fan_team_is_role_marked(self):
        """Verify the fan-role Team FK is role-marked from birth — no
        unmarked `team` column on a new produced file."""
        assert "fan_team" in COMMENT_SAMPLES_SCHEMA.names()
        assert "team" not in COMMENT_SAMPLES_SCHEMA.names()

    def test_excludes_rejected_columns(self):
        """Verify decided-out columns stay out (author, confidence)."""
        for col in ("author", "confidence"):
            assert col not in COMMENT_SAMPLES_SCHEMA.names()

    def test_joins_outputs_but_not_views(self):
        """Verify comment_samples ships via DASHBOARD_OUTPUT_SCHEMAS only — a
        fact subset (no measures), not a rollup; the rollup mapping stays
        rollup-only."""
        assert DASHBOARD_OUTPUT_SCHEMAS["comment_samples"] is COMMENT_SAMPLES_SCHEMA
        assert "comment_samples" not in AGGREGATE_VIEW_SCHEMAS

    def test_fact_side_dtypes_derive_from_sentiment(self):
        """Verify every column carried verbatim from the fact keeps the
        fact's dtype (no drift between the subset and its source)."""
        for col in ("comment_id", "link_id", "body", "score", "created_utc"):
            assert COMMENT_SAMPLES_SCHEMA[col] == SENTIMENT_SCHEMA[col]


class TestRostersContract:
    """Contract guards for the roster snapshot reference asset."""

    def test_conforming_frame_passes(self, roster_frame):
        """Verify a frame matching ROSTERS_SCHEMA validates without raising."""
        validate_schema(roster_frame, ROSTERS_SCHEMA, "rosters.parquet")

    def test_pins_height_and_weight(self):
        """Verify the bio columns are in the contract (the re-snapshot's point)."""
        assert ROSTERS_SCHEMA["height"] == pl.String
        assert ROSTERS_SCHEMA["weight"] == pl.String

    def test_birth_date_is_date_typed(self):
        """Verify birth_date lands as a real Date, not the endpoint's raw string."""
        assert ROSTERS_SCHEMA["birth_date"] == pl.Date


class TestManifestContract:
    """The manifest's typed shape and the vocabularies it publishes."""

    def test_blocks_in_order(self):
        """Identity, rules, season facts, registry: the four blocks, in
        that order, so the file reads top-down and the TS type mirrors it."""
        assert list(Manifest.__annotations__) == [
            "schema_version",
            "season",
            "generated_at",
            "config_versions",
            "classifiers",
            "snapshots",
            "rules",
            "calendar",
            "corpus",
            "populations",
            "tables",
        ]

    def test_table_populations_enumerate_every_output(self):
        """Every produced table names its population (or None), so a new
        output can't ship without saying what it sums to."""
        assert set(TABLE_POPULATIONS) == set(DASHBOARD_OUTPUT_SCHEMAS)

    def test_fact_tables_draw_from_a_defined_population(self):
        """The fact rollups and the samples subset each name a population
        that POPULATIONS defines."""
        for name in [*AGGREGATE_VIEW_SCHEMAS, "comment_samples"]:
            assert TABLE_POPULATIONS[name] in POPULATIONS, name

    def test_dimensions_hold_no_comments(self):
        """Dimensions and reference tables have no comment universe."""
        for name in ("players", "teams", "games", "player_games", "posts"):
            assert TABLE_POPULATIONS[name] is None, name

    def test_corpus_daily_columns_are_corpus_stages(self):
        """Each count column is a funnel stage under the corpus block's own
        key, so a column sums to the figure of the same name; the table
        has no single population."""
        assert TABLE_POPULATIONS["corpus_daily"] is None
        assert set(CORPUS_DAILY_SCHEMA.names()[1:]) < set(CORPUS_STAGES)

    def test_the_three_universes_differ(self):
        """The populations the spike found disagreeing are three names."""
        assert TABLE_POPULATIONS["player_overall"] == "attributed"
        assert TABLE_POPULATIONS["player_fan_team"] == "attributed_flaired"
        assert TABLE_POPULATIONS["fan_team_overall"] == "flaired"
        assert TABLE_POPULATIONS["game_sentiment"] == "in_thread"

    def test_corpus_stages_are_the_funnel(self):
        """The corpus block's keys are the funnel stages, each a defined
        population; the first stages are the ones season.yaml records."""
        assert tuple(Corpus.__annotations__) == CORPUS_STAGES
        assert CORPUS_STAGES[: len(CORPUS_KEYS)] == CORPUS_KEYS
        for stage in CORPUS_STAGES:
            assert stage in POPULATIONS, stage

    def test_metric_formulas_cover_the_rate_columns(self):
        """Every rate measure on the views has a published formula."""
        rate_columns = {
            col for col, dtype in PLAYER_OVERALL_SCHEMA.items() if dtype == pl.Float64
        }
        assert set(METRIC_FORMULAS) == rate_columns

    def test_polarization_is_the_non_neutral_share(self):
        """The name promises a split measure; the formula says what it is."""
        assert (
            METRIC_FORMULAS["polarization"] == "(pos_count + neg_count) / comment_count"
        )


class TestLoadManifest:
    """Tests for load_manifest, the contract's read side."""

    @pytest.fixture
    def manifest_dict(self) -> dict:
        """Every Manifest block present, values as the writer shapes them."""
        return {
            "schema_version": 5,
            "season": "2025-26",
            "generated_at": "2026-09-16T12:00:00+00:00",
            "config_versions": {"players": "4.5"},
            "classifiers": {},
            "snapshots": {"games_fetched_at": None},
            "rules": {},
            "calendar": {"opening_night": "2025-10-21"},
            "corpus": {"classified": 6},
            "populations": {},
            "tables": {
                "player_overall": {
                    "file": "player_overall.parquet",
                    "rows": 2,
                    "population": "attributed",
                }
            },
        }

    def test_round_trips_the_written_file(self, tmp_path, manifest_dict):
        """What the aggregation script writes reads back as the same dict."""
        # Arrange
        path = tmp_path / "manifest.json"
        with open(path, "w") as f:
            json.dump(manifest_dict, f, indent=2)

        # Act
        manifest = load_manifest(path)

        # Assert
        assert manifest == manifest_dict
        assert list(manifest) == list(Manifest.__annotations__)

    def test_missing_block_raises(self, tmp_path, manifest_dict):
        """A file without one of the contract's blocks names it and the path."""
        # Arrange
        del manifest_dict["tables"]
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(manifest_dict))

        # Act / Assert
        with pytest.raises(ValueError, match="tables") as exc:
            load_manifest(path)
        assert str(path) in str(exc.value)

    def test_non_object_raises(self, tmp_path):
        """A JSON document that is not an object is not a manifest."""
        # Arrange
        path = tmp_path / "manifest.json"
        path.write_text("[]")

        # Act / Assert
        with pytest.raises(ValueError, match="object"):
            load_manifest(path)


class TestValidateSchema:
    """Tests for validate_schema fail-fast behavior and diagnostics."""

    def test_conforming_frame_passes(self, sentiment_frame):
        """Verify a frame matching the schema validates without raising."""
        # Arrange / Act / Assert — no exception is the assertion
        validate_schema(sentiment_frame, SENTIMENT_SCHEMA, "sentiment.parquet")

    def test_missing_column_raises(self, sentiment_frame):
        """Verify a dropped column is reported by name."""
        # Arrange
        df = sentiment_frame.drop("score")

        # Act / Assert
        with pytest.raises(ValueError, match="sentiment.parquet") as exc:
            validate_schema(df, SENTIMENT_SCHEMA, "sentiment.parquet")
        assert "missing columns" in str(exc.value)
        assert "score" in str(exc.value)

    def test_extra_column_raises(self, sentiment_frame):
        """Verify an unexpected column is reported by name."""
        # Arrange
        df = sentiment_frame.with_columns(pl.lit(1).alias("bonus"))

        # Act / Assert
        with pytest.raises(ValueError, match="sentiment.parquet") as exc:
            validate_schema(df, SENTIMENT_SCHEMA, "sentiment.parquet")
        assert "extra columns" in str(exc.value)
        assert "bonus" in str(exc.value)

    def test_dtype_mismatch_raises(self, sentiment_frame):
        """Verify a wrong dtype is reported with expected and actual types."""
        # Arrange
        df = sentiment_frame.with_columns(pl.col("score").cast(pl.Int32))

        # Act / Assert
        with pytest.raises(ValueError, match="sentiment.parquet") as exc:
            validate_schema(df, SENTIMENT_SCHEMA, "sentiment.parquet")
        message = str(exc.value)
        assert "score" in message
        assert "Int64" in message
        assert "Int32" in message

    def test_column_order_mismatch_raises(self, sentiment_frame):
        """Verify reordered columns fail with an order-specific diagnostic."""
        # Arrange
        df = sentiment_frame.select(list(reversed(SENTIMENT_SCHEMA.names())))

        # Act / Assert
        with pytest.raises(ValueError, match="sentiment.parquet") as exc:
            validate_schema(df, SENTIMENT_SCHEMA, "sentiment.parquet")
        assert "column order" in str(exc.value)
