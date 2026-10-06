"""
Schema contracts for produced data files and cached reference assets.

Single source of truth for column names and dtypes of every file the
pipeline produces. Data dictionary first, enforcement second:

- SENTIMENT_SCHEMA is enforced at the sentiment.parquet write boundary
  (pipeline/results.py) and again as a read-side guard in
  pipeline/aggregation.py.
- The aggregate-view schemas describe the fact rollups; they are
  enforced in aggregate_sentiment() before the views are returned for
  writing.
- ROSTERS_SCHEMA describes the season roster snapshot — a reference
  asset (pipeline ingredient, not a published output) enforced at the
  fetch write boundary (scripts/fetch_rosters.py).
- TEAM_GAME_LOG_SCHEMA / PLAYER_GAME_LOG_SCHEMA describe the season
  game-log snapshots from stats.nba.com (scripts/fetch_games.py), the
  reference assets the game tables derive from.
- LIVE_PLAY_BY_PLAY_SCHEMA describes the per-game snapshots of the
  liveData play-by-play (scripts/fetch_live_play_by_play.py), enforced
  at the fetch write boundary.
- GAMES_SCHEMA / PLAYER_GAMES_SCHEMA describe the game layer
  (games.parquet, player_games.parquet): the Game dimension and the
  per-player box-score lines, derived from the snapshots under the
  active config (pipeline/games.py); enforced via the unified loop.
- POSTS_SCHEMA describes the Post bridge: the full bridge
  (reference/posts_bridge.parquet, every post, enforced at the build
  write boundary in scripts/process_posts.py) and its published subset
  (posts.parquet, enforced via the unified loop).
- PLAYERS_SCHEMA describes the Player dimension (players.parquet),
  config curation joined with snapshot facts; enforced in
  aggregate_sentiment() via the unified DASHBOARD_OUTPUT_SCHEMAS loop.
- TARGET_POOL_SCHEMA / SENTIMENT_TARGETS_SCHEMA describe the target
  verifier's pool and its verdict sidecar (pipeline/receipts.py,
  pipeline/results.py).
- COMMENT_SAMPLES_SCHEMA describes the comment-samples fact subset
  (comment_samples.parquet): verbatim rows of the fact, selected not
  aggregated; enforced via the same unified loop.
- CORPUS_DAILY_SCHEMA describes the corpus funnel at day grain
  (corpus_daily.parquet), built from the raw download by
  pipeline/corpus.py and cached as a reference snapshot.
- ACCURACY_SAMPLE_SCHEMA describes the accuracy sample
  (reference/accuracy_sample.parquet): manual verdicts on a blind
  random draw of the attributed population beside the classifier's
  labels for the same rows (pipeline/accuracy.py); enforced at the
  import write boundary.
- NULLABLE_COLUMNS declares, per produced table, which columns may hold
  nulls; every other column is enforced null-free at the same write
  boundary (validate_nullability).
- RECAP_FRAME_SCHEMAS / RECAP_NULLABLE_COLUMNS describe the frames of a
  recap file (pipeline/recaps.py): tables serialized as column arrays
  inside one JSON document per curated recap, validated like every
  produced table before serialization. RecapHeader is the document's
  scalar block, RecapEntry its manifest registry entry.
- Manifest is the typed shape of manifest.json, the front door written
  beside the parquets (pipeline/aggregation.py builds it): rules,
  identity and existence, never results.

This module must not import from other pipeline modules (it is imported
by them).
"""

import json
from pathlib import Path
from typing import TypedDict, cast

import polars as pl

from utils.constants import RECAPS_SUBDIR

# Bump on any breaking change to a produced-file contract.
SCHEMA_VERSION = 11

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
        # (pipeline/results.py) - NOT projected from the filtered NDJSON.
        # mentioned_text is parallel: the body's substring that matched each name
        "mentioned_players": pl.List(pl.String),
        "mentioned_text": pl.List(pl.String),
        "sentiment": pl.String,  # "pos" | "neg" | "neu" | "error"
        "confidence": pl.Float64,
        "sentiment_player": pl.String,  # nullable
        # Config-versioned derivations materialized at assembly, stamped with
        # players_config_version / teams_config_version in the file metadata
        "attributed_player": pl.String,  # nullable; resolve_player()
        "fan_team": pl.String,  # nullable; fan role of Team, from flair
        "input_tokens": pl.Int64,
        "output_tokens": pl.Int64,
    }
)

# --- Construction-side schemas, derived from SENTIMENT_SCHEMA ---------------
# The joined frame is assembled from two file inputs plus four assembly-derived
# columns: mentioned_players / mentioned_text are recomputed from body at
# assembly time, and attributed_player / fan_team are resolved from them and
# from the flair, so neither input schema carries them. Deriving the input schemas from
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

# The box-score line as LeagueGameLog serves it, shared by the team and
# player logs and carried verbatim onto player_games. Percentages and
# fantasy points are derivable and stay out.
_BOX_SCORE_COLUMNS: dict[str, pl.DataType] = {
    "minutes": pl.Int64,
    "fgm": pl.Int64,
    "fga": pl.Int64,
    "fg3m": pl.Int64,
    "fg3a": pl.Int64,
    "ftm": pl.Int64,
    "fta": pl.Int64,
    "oreb": pl.Int64,
    "dreb": pl.Int64,
    "reb": pl.Int64,
    "ast": pl.Int64,
    "stl": pl.Int64,
    "blk": pl.Int64,
    "tov": pl.Int64,
    "pf": pl.Int64,
    "pts": pl.Int64,
    "plus_minus": pl.Int64,
}

# data/<season>/reference/team_game_log.parquet — one row per game x team,
# the LeagueGameLog team lines across every season type (pipeline/
# nba_stats.py). A faithful capture at the endpoint's own grain: both
# sides of every game, non-NBA preseason opponents included; the game
# tables, not the snapshot, decide what ships. season_type is the
# endpoint label the row was fetched under ("Regular Season", "IST",
# ...); the Cup final is the one game that lives only under "IST".
TEAM_GAME_LOG_SCHEMA = pl.Schema(
    {
        "season_type": pl.String,
        "game_id": pl.String,  # 10 digits; prefix encodes the season type
        "game_date": pl.Date,
        "team_id": pl.Int64,
        "team_abbr": pl.String,
        "team_name": pl.String,
        "matchup": pl.String,  # "BOS vs. NYK" at home, "BOS @ NYK" away
        "wl": pl.String,
        **_BOX_SCORE_COLUMNS,
    }
)

# data/<season>/reference/player_game_log.parquet — one row per game x
# player, every player who dressed (not just the tracked set, so a
# players.yaml roster bump never needs a re-fetch).
PLAYER_GAME_LOG_SCHEMA = pl.Schema(
    {
        "season_type": pl.String,
        "game_id": pl.String,
        "game_date": pl.Date,
        "player_id": pl.Int64,
        "player_name": pl.String,  # endpoint spelling; the join key is player_id
        "team_id": pl.Int64,
        "team_abbr": pl.String,
        "matchup": pl.String,
        "wl": pl.String,  # nullable at source
        **_BOX_SCORE_COLUMNS,
    }
)

# data/<season>/reference/play_by_play_live/<game_id>.parquet — one row per
# action_number, the liveData feed as served: every field, snake_cased,
# nothing filtered, in feed order (order_number). Fields vary by action
# type and an absent field is null. time_actual is when the scorer logged
# the action, UTC to a tenth of a second, and is not strictly ordered;
# clock is an ISO duration and the running score is a string on every row.
# A block or steal is its own row with its own action_number.
LIVE_PLAY_BY_PLAY_SCHEMA = pl.Schema(
    {
        "game_id": pl.String,
        "action_number": pl.Int64,  # unique within a game: the row key
        "clock": pl.String,
        "time_actual": pl.String,  # "2026-05-31T00:23:08.2Z"
        "period": pl.Int64,
        "period_type": pl.String,  # "REGULAR" / "OVERTIME"
        "action_type": pl.String,
        "sub_type": pl.String,
        "qualifiers": pl.List(pl.String),  # "mandatory" on a timeout
        "person_id": pl.Int64,  # 0 on actions without a player
        "x": pl.Float64,  # percent of court; null off a shot
        "y": pl.Float64,
        "possession": pl.Int64,  # team id; 0 when nobody holds the ball
        "score_home": pl.String,
        "score_away": pl.String,
        "edited": pl.String,  # last edit, UTC to the second
        "order_number": pl.Int64,  # feed order
        "is_target_score_last_period": pl.Boolean,
        "x_legacy": pl.Int64,  # shot-chart coordinates; null off a shot
        "y_legacy": pl.Int64,
        "is_field_goal": pl.Int64,
        "side": pl.String,
        "description": pl.String,
        "person_ids_filter": pl.List(pl.Int64),  # everyone the action names
        "team_id": pl.Int64,
        "team_tricode": pl.String,
        "descriptor": pl.String,
        "jump_ball_recovered_name": pl.String,
        "jump_ball_recoverd_person_id": pl.Int64,  # the feed's spelling
        "player_name": pl.String,
        "player_name_i": pl.String,
        "jump_ball_won_player_name": pl.String,
        "jump_ball_won_person_id": pl.Int64,
        "jump_ball_lost_player_name": pl.String,
        "jump_ball_lost_person_id": pl.Int64,
        "area": pl.String,
        "area_detail": pl.String,
        "shot_distance": pl.Float64,
        "shot_result": pl.String,  # "Made" / "Missed"
        "points_total": pl.Int64,  # running totals are the player's, in this game
        "turnover_total": pl.Int64,
        "steal_player_name": pl.String,
        "steal_person_id": pl.Int64,  # on the turnover the steal ends
        "official_id": pl.Int64,
        "foul_personal_total": pl.Int64,
        "foul_technical_total": pl.Int64,
        "foul_drawn_player_name": pl.String,
        "foul_drawn_person_id": pl.Int64,
        "assist_player_name_initial": pl.String,
        "assist_person_id": pl.Int64,
        "assist_total": pl.Int64,
        "shot_action_number": pl.Int64,  # the shot a rebound follows
        "rebound_total": pl.Int64,
        "rebound_defensive_total": pl.Int64,
        "rebound_offensive_total": pl.Int64,
        "block_player_name": pl.String,
        "block_person_id": pl.Int64,  # on the shot the block ends
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

# Every player-keyed view carries the Player dimension's stable id right
# after its display key, so consumers join on either.
PLAYER_OVERALL_SCHEMA = pl.Schema(
    {"attributed_player": pl.String, "player_id": pl.Int64, **_METRIC_COLUMNS}
)

PLAYER_TEMPORAL_SCHEMA = pl.Schema(
    {
        "attributed_player": pl.String,
        "player_id": pl.Int64,
        "week": pl.Datetime("us"),  # pl.from_epoch(...).dt.truncate("1w"), no tz
        **_METRIC_COLUMNS,
    }
)

PLAYER_FAN_TEAM_SCHEMA = pl.Schema(
    {
        "attributed_player": pl.String,
        "player_id": pl.Int64,
        "fan_team": pl.String,
        **_METRIC_COLUMNS,
    }
)

FAN_TEAM_OVERALL_SCHEMA = pl.Schema(
    {
        "fan_team": pl.String,
        **_METRIC_COLUMNS,
        "abbreviation": pl.String,  # enrichment from config/teams.yaml
        "conference": pl.String,
        "logo_url": pl.String,
    }
)

# Player x Game: the room's verdict on a player in one game's threads
# (game + post-game merged per game_id). Fact rows reach a game through
# posts (link_id = post_id -> game_id). Counts only — the display
# baseline and floor are consumer choices. Box scores are not
# pre-joined: player_games joins on (game_id, attributed_player).
GAME_SENTIMENT_SCHEMA = pl.Schema(
    {
        "attributed_player": pl.String,  # FK -> players.parquet
        "player_id": pl.Int64,
        "game_id": pl.String,  # FK -> games.parquet
        **_METRIC_COLUMNS,
        "thread_comment_count": pl.Int64,  # usable fact rows in the game's threads, all players
    }
)

# View name -> schema for the aggregate *views* (fact-table rollups).
# Keys match aggregate_sentiment() return-dict keys and parquet filenames.
# Deliberately fact-only: dimensions live in DASHBOARD_OUTPUT_SCHEMAS
# below.
AGGREGATE_VIEW_SCHEMAS: dict[str, pl.Schema] = {
    "player_overall": PLAYER_OVERALL_SCHEMA,
    "player_temporal": PLAYER_TEMPORAL_SCHEMA,
    "player_fan_team": PLAYER_FAN_TEAM_SCHEMA,
    "fan_team_overall": FAN_TEAM_OVERALL_SCHEMA,
    "game_sentiment": GAME_SENTIMENT_SCHEMA,
}

# --- Player dimension (enforced in pipeline/aggregation.py) ------------------
# One row per attributed player — the Player dimension the views'
# attributed_player FK references. Materialized as players.parquet. The
# config side is curated in config/<season>/players.yaml; the snapshot
# side LEFT JOINs from the season's rosters.parquet on player_id, so
# snapshot gaps surface as nulls, never dropped rows.
# NOTE: roster_team is the *roster* role (who the player plays for),
# distinct from the fan role (fan_team) on player_fan_team and
# fan_team_overall.

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

# Derived at build from attributed_player (utils.formatting.slugify): the
# frontend's URL identity, read never re-derived. Asserted unique.
PLAYERS_DERIVED_COLUMNS: dict[str, pl.DataType] = {"slug": pl.String}

PLAYERS_SCHEMA = pl.Schema(
    {
        "attributed_player": PLAYERS_CONFIG_COLUMNS["attributed_player"],
        **PLAYERS_DERIVED_COLUMNS,
        **{k: v for k, v in PLAYERS_CONFIG_COLUMNS.items() if k != "attributed_player"},
        **{col: ROSTERS_SCHEMA[col] for col in PLAYERS_SNAPSHOT_COLUMNS},
    }
)

# --- Team dimension (enforced in pipeline/aggregation.py) -------------------
# One row per franchise — the Team dimension every role-marked FK
# references (fan_team on the fan views, roster_team on players and
# player_games, home_team/away_team on games).
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

# --- Game layer (built in pipeline/games.py, enforced in aggregation) -------
# games.parquet: the Game dimension, one row per game, pivoted from the
# team game log. Team FKs carry the canonical `team` name (the Team
# dimension's key) in the home and away roles. On a neutral-site game
# both team lines list the opponent as host; sides are then assigned by
# team_id so the row does not depend on endpoint order. Playoff fields
# parse from the id (004 YY 00 R S G) and are null otherwise.

GAMES_SCHEMA = pl.Schema(
    {
        "game_id": pl.String,
        "game_date": pl.Date,
        "season_type": pl.String,  # pre_season | regular_season | play_in | playoffs
        "nba_cup_final": pl.Boolean,  # regular_season window, its own game id
        "neutral_site": pl.Boolean,
        "home_team": pl.String,  # FK -> teams.parquet, home role
        "away_team": pl.String,  # FK -> teams.parquet, away role
        "home_score": pl.Int64,
        "away_score": pl.Int64,
        "winner": pl.String,  # FK -> teams.parquet
        "playoff_round": pl.Int64,
        "playoff_series": pl.Int64,
        "playoff_game": pl.Int64,
    }
)

# player_games.parquet: one row per game x tracked player who dressed.
# `roster_team` is the player's team on that line — the dated roster
# edge, distinct from players.roster_team (season-end). Absent lines are
# absent, never fabricated. PK (game_id, attributed_player).
PLAYER_GAMES_SCHEMA = pl.Schema(
    {
        "game_id": pl.String,  # FK -> games.parquet
        "attributed_player": pl.String,  # FK -> players.parquet
        "player_id": pl.Int64,
        "roster_team": pl.String,  # FK -> teams.parquet, dated roster role
        "opponent": pl.String,  # FK -> teams.parquet
        "is_home": pl.Boolean,  # roster_team == games.home_team; null on a neutral site
        "wl": pl.String,
        **_BOX_SCORE_COLUMNS,
    }
)

# --- Post bridge (built in pipeline/posts.py) --------------------------------
# One row per r/NBA post. post_id is the t3_ fullname, the fact's link_id,
# so the comment -> game path is one join. post_type derives from flair
# (title as fallback), source from the leading tag of a news post;
# game_id from the title's team pair and the ET date of created_utc,
# validated against games.parquet, on threads only. Split, second-half
# and repost threads share a game_id; is_primary marks the largest by
# num_comments per (game_id, post_type). The published subset keeps the
# game and post-game threads plus every post a receipt points at.
POSTS_SCHEMA = pl.Schema(
    {
        "post_id": pl.String,
        "title": pl.String,
        "created_utc": pl.Int64,  # epoch seconds, as the source
        "score": pl.Int64,
        "num_comments": pl.Int64,  # whole-room size; sum per game for a game's room
        "link_flair_text": pl.String,  # as the source
        # game_thread | post_game_thread | highlight | lowlight | injury |
        # news | discussion | other
        "post_type": pl.String,
        "source": pl.String,  # reporter, outlet or person quoted; news only
        "game_id": pl.String,  # FK -> games.parquet; null when unlinked
        "is_primary": pl.Boolean,  # false whenever game_id is null
    }
)

# --- Comment samples: fact subset (enforced in pipeline/aggregation.py) ------
# One row per sampled comment: verbatim fact rows, top-N per player x
# sentiment by score (see build_comment_samples). PK (attributed_player,
# sentiment, rank). body is never truncated. No author, no confidence.
COMMENT_SAMPLES_SCHEMA = pl.Schema(
    {
        "attributed_player": pl.String,  # FK -> players.parquet
        "player_id": pl.Int64,
        "sentiment": pl.String,  # "pos" | "neg" | "neu", as the fact
        "rank": pl.Int64,  # 1..N within (attributed_player, sentiment)
        "comment_id": pl.String,  # provenance back to the fact
        "link_id": pl.String,  # -> Reddit permalink, with comment_id
        "body": pl.String,  # the receipt, verbatim
        "score": pl.Int64,
        "created_utc": pl.Int64,  # epoch seconds, as the fact
        "fan_team": pl.String,  # fan role of Team, role-marked
    }
)

# The target-verifier pool (data/<season>/batches/<stage>/pool.parquet):
# which comments were sent to the verifier and why. attributed_player and
# rank are pool-time snapshots under the config the pool was built with.
TARGET_POOL_SCHEMA = pl.Schema(
    {
        "comment_id": pl.String,  # FK -> sentiment.parquet; the request custom_id
        "attributed_player": pl.String,  # at pool time
        "sentiment": pl.String,  # "pos" | "neg", the prompt input
        "stratum": pl.String,  # candidate | random_named | random_null
        "rank": pl.Int64,  # candidate rank within the cell; null for strata rows
    }
)

# The verifier's verdicts (data/<season>/processed/sentiment_targets.parquet):
# the pool joined to the model's response, one row per verified comment.
# target_raw is the model's string, frozen; resolution to a canonical
# player is config-derived and happens at aggregation.
SENTIMENT_TARGETS_SCHEMA = pl.Schema(
    {
        **TARGET_POOL_SCHEMA,
        "target_raw": pl.String,  # nullable: null = no player target
        "target_confidence": pl.Float64,
        "valid": pl.Boolean,  # False = the response did not parse
        "input_tokens": pl.Int64,
        "output_tokens": pl.Int64,
    }
)

ACCURACY_SAMPLE_SCHEMA = pl.Schema(
    {
        "comment_id": pl.String,
        "group": pl.String,  # a pipeline.accuracy.GROUPS value
        "position": pl.Int64,  # draw order, 0-based
        "mention_count": pl.Int64,  # names the row's target list offered
        # The classifier's side, copied from the fact at draw time
        "sentiment": pl.String,  # "pos" | "neg" | "neu"
        "confidence": pl.Float64,
        "sentiment_player": pl.String,  # nullable: the classifier's named target
        "attributed_player": pl.String,  # the resolution the row was drawn on
        # The manual side; the labels are null on unlabeled and rejected rows
        "labeled": pl.Boolean,  # a verdict or a reject was entered
        "label_sentiment": pl.String,  # nullable
        "label_target": pl.String,  # nullable: a canonical name, "none" or "other"
        "reject": pl.String,  # nullable: a pipeline.accuracy.REJECT_REASONS value
        "needed_context": pl.Boolean,  # the note says the thread decided it
        "unsure": pl.Boolean,  # the note says it was a coin flip
        "note": pl.String,  # nullable
    }
)

# --- Corpus at day grain (built in pipeline/corpus.py) -----------------------
# One row per UTC day of the download's extent, zero-filled: the funnel's
# stages as counts, named exactly as the manifest's corpus block so each
# column sums to the figure of the same name. Counts only; rolling means
# are a display choice. The window is ET-midnight and the days are UTC,
# so the last day is a stub; the grid follows the data, not the
# calendar, so that the sums hold. attributed is null throughout until
# the season's fact carries materialized attribution.
CORPUS_DAILY_SCHEMA = pl.Schema(
    {
        "day": pl.Date,
        "raw_comments": pl.Int64,
        "population_submitted": pl.Int64,
        "usable": pl.Int64,
        "attributed": pl.Int64,
    }
)

# Every table the aggregation stage produces -> its schema, across the
# classes of produced table: the fact rollups (AGGREGATE_VIEW_SCHEMAS),
# the Player and Team dimensions, the game layer (Game dimension +
# per-player box-score lines, the Post bridge), and the comment-samples
# fact subset.
# Single source for aggregate_sentiment()'s unified validation loop and the
# script's parquet write loop (<name>.parquet).
DASHBOARD_OUTPUT_SCHEMAS: dict[str, pl.Schema] = {
    **AGGREGATE_VIEW_SCHEMAS,
    "players": PLAYERS_SCHEMA,
    "teams": TEAMS_SCHEMA,
    "games": GAMES_SCHEMA,
    "player_games": PLAYER_GAMES_SCHEMA,
    "posts": POSTS_SCHEMA,
    "comment_samples": COMMENT_SAMPLES_SCHEMA,
    "corpus_daily": CORPUS_DAILY_SCHEMA,
}

# Which columns of each produced table may hold nulls. Polars schemas
# carry names and dtypes only, and parquet marks every column nullable,
# so this registry is the contract's one declaration: enforced at the
# write boundary (validate_nullability) and published in schema.json.
# Every output is enumerated; an empty set means no column may be null.
NULLABLE_COLUMNS: dict[str, frozenset[str]] = {
    "player_overall": frozenset(),
    "player_temporal": frozenset(),
    "player_fan_team": frozenset(),
    "fan_team_overall": frozenset(),
    "game_sentiment": frozenset(),
    # A player off every roster at season end has no team, no conference
    # and no snapshot line: config and snapshot sides null together
    "players": frozenset({"roster_team", "conference", *PLAYERS_SNAPSHOT_COLUMNS}),
    "teams": frozenset(),
    "games": frozenset({"playoff_round", "playoff_series", "playoff_game"}),
    "player_games": frozenset({"is_home"}),  # neutral site: nobody hosted
    "posts": frozenset({"game_id", "link_flair_text", "source"}),
    "comment_samples": frozenset({"fan_team"}),  # unflaired commenter
    "corpus_daily": frozenset({"attributed"}),
}

# --- Recap files (built in pipeline/recaps.py) -------------------------------
# One JSON document per curated recap: a scalar header (RecapHeader) and
# named frames, each a table serialized as column arrays under its name.
# The frames are validated like every produced table before they are
# serialized, and schema.json describes them under documents.recap with
# the tables' column vocabulary. Time is two clocks: game_seconds since
# tip-off (720 per period, 300 per overtime) and wall_clock, epoch
# seconds; a play's wall clock is its own timestamp in the feed, a
# comment's game seconds is interpolated between the plays either side
# of it. How long the room takes to react is measured once per season
# under rules.recaps.reaction_lag, never per file. The plays are the
# game as scored on the night: corrections made afterwards reach the
# box score, never the feed. Team columns keep the feed's abbreviation
# under its own name; a comment carries the fan role; there is no bare
# team.

# The game clock: one row per period, start and end wall clock from the
# period markers' own timestamps, game seconds cumulative across periods.
RECAP_PERIODS_SCHEMA = pl.Schema(
    {
        "period": pl.Int64,
        "start_seconds": pl.Int64,
        "end_seconds": pl.Int64,
        "start_wall": pl.Int64,  # epoch seconds, the start marker's timestamp
        "end_wall": pl.Int64,
        "start_action_number": pl.Int64,
        "end_action_number": pl.Int64,
    }
)

# The live threads the comments were drawn from, primary and split.
RECAP_THREADS_SCHEMA = pl.Schema(
    {
        "post_id": pl.String,  # FK -> posts.parquet; title joins from there
        "is_primary": pl.Boolean,
        "created_utc": pl.Int64,
        "num_comments": pl.Int64,  # the whole room, as posts.parquet
        "comment_n": pl.Int64,  # classified rows in this recap from the thread
    }
)

# Every player's on-court intervals in game seconds, in game order. The
# feed logs substitutions and never the opening five, so each player's
# first-period opening state is inferred from his own rows; the build
# checks the result against the box score's minutes and against five on
# the floor per team.
RECAP_STINTS_SCHEMA = pl.Schema(
    {
        "person_id": pl.Int64,
        "team_tricode": pl.String,
        "period": pl.Int64,
        "start_seconds": pl.Int64,
        "end_seconds": pl.Int64,
    }
)

# The game's plays: every row of the feed but its closing one, in feed
# order. kind is the feed's action type under the recap's vocabulary; a
# substitution is a sub_in or sub_out row naming its own player; a block
# or steal follows the play it ended and points at it, and a block
# borrows its shot's location. x and y are the feed's full-court
# position, 0-100 along and across the court, so x says which basket a
# team attacks. A player's line is counted from the rows: field goals
# are 2pt and 3pt rows and free throws freethrow rows, by made;
# rebounds are rebound rows naming a player, offensive or defensive by
# sub_type; assists a made shot's assist_person_id; steals, blocks and
# turnovers their own rows naming a player; personal fouls foul rows
# except sub_type technical.
RECAP_PLAYS_SCHEMA = pl.Schema(
    {
        "action_number": pl.Int64,  # unique within the game: the row key
        "paired_action_number": pl.Int64,  # nullable: the play a block or steal ends
        "period": pl.Int64,
        "clock": pl.String,  # as the feed serves it
        "game_seconds": pl.Int64,
        "wall_clock": pl.Int64,  # epoch seconds, the play's own timestamp
        "kind": pl.String,
        "action_type": pl.String,
        "sub_type": pl.String,
        "description": pl.String,
        "team_tricode": pl.String,  # nullable: a period marker
        "person_id": pl.Int64,  # 0 on team actions
        "player_name_i": pl.String,  # nullable: a team action
        "assist_person_id": pl.Int64,  # nullable: off an assisted make
        "is_focus": pl.Boolean,
        "made": pl.Boolean,  # nullable: not a shot
        "shot_value": pl.Int64,  # 3, 2, 1, or 0 off a shot
        "x": pl.Float64,  # nullable: off a located play
        "y": pl.Float64,
        "shot_distance": pl.Float64,
        "score_home": pl.Int64,  # on every row
        "score_away": pl.Int64,
    }
)

# Every classified comment in the live threads, on both clocks. body is
# kept by rule (the focus player's comments and the room's top-voted per
# bucket) and never truncated; a kept body is the comment verbatim.
RECAP_COMMENTS_SCHEMA = pl.Schema(
    {
        "comment_id": pl.String,
        "post_id": pl.String,  # -> threads
        "created_utc": pl.Int64,
        "game_seconds": pl.Int64,  # interpolated between the plays either side
        "phase": pl.String,  # pre | live | break | post
        "sentiment": pl.String,
        "score": pl.Int64,
        "fan_team": pl.String,  # nullable: unflaired commenter
        "player_id": pl.Int64,  # nullable: whom the sentiment is about -> players
        "is_focus": pl.Boolean,  # attributed_player is the focus player
        "body": pl.String,  # nullable: outside the selection rule
    }
)

# Frame name -> schema, in document order.
RECAP_FRAME_SCHEMAS: dict[str, pl.Schema] = {
    "periods": RECAP_PERIODS_SCHEMA,
    "threads": RECAP_THREADS_SCHEMA,
    "stints": RECAP_STINTS_SCHEMA,
    "plays": RECAP_PLAYS_SCHEMA,
    "comments": RECAP_COMMENTS_SCHEMA,
}

RECAP_NULLABLE_COLUMNS: dict[str, frozenset[str]] = {
    "periods": frozenset(),
    "threads": frozenset(),
    "stints": frozenset(),
    "plays": frozenset(
        {
            "paired_action_number",
            "team_tricode",
            "player_name_i",
            "assist_person_id",
            "made",
            "x",
            "y",
            "shot_distance",
        }
    ),
    "comments": frozenset({"fan_team", "player_id", "body"}),
}

# The population every recap's comments draw from (a POPULATIONS key).
RECAP_POPULATION = "live_thread"


def recap_file(key: str) -> str:
    """The manifest-registered path of a recap, relative to the dashboard."""
    return f"{RECAPS_SUBDIR}/{key}.json"


# --- Manifest (built in pipeline/aggregation.py) ------------------------------
# The one file the frontend fetches first, which makes everything else
# self-describing. Invariant: nothing in it is queryable from the tables
# it fronts, so it can never disagree with them. The one exception is
# the recap registry entry, a rollup of its own file built in the same
# pass, so an index renders without opening one. TypedDicts, so the
# shape is one JSON-serializable contract and the first TS-codegen
# target. Key order is block order: identity, rules, season facts,
# table and recap registries.

# The rate measures as text formulas over the count columns, for the
# methodology captions. polarization is the non-neutral share.
METRIC_FORMULAS: dict[str, str] = {
    "neg_rate": "neg_count / comment_count",
    "pos_rate": "pos_count / comment_count",
    "net_sentiment": "(pos_count - neg_count) / comment_count",
    "polarization": "(pos_count + neg_count) / comment_count",
}

# The comment populations by name: the corpus funnel's stages, then the
# universes the fact tables draw from. Every corpus count and every
# table's population is one of these, so "which total" is never a guess.
POPULATIONS: dict[str, str] = {
    "raw_comments": "every r/NBA comment downloaded for the season window",
    "population_submitted": (
        "raw comments that mention a tracked player, as submitted to the "
        "sentiment classifier"
    ),
    "classified": (
        "submitted comments with a classifier response: the rows of sentiment.parquet"
    ),
    "usable": "classified comments minus classifier errors",
    "attributed": "usable comments resolved to one tracked player",
    "flaired": "usable comments whose author carries a team flair, attributed or not",
    "attributed_flaired": "attributed comments whose author carries a team flair",
    "in_thread": "attributed comments posted in a game or post-game thread",
    "live_thread": (
        "usable comments posted in a game's live game threads, primary and split"
    ),
}

# The funnel, in order. The first stages are relayed from season.yaml;
# the rest are derived from sentiment.parquet at build, never transcribed.
CORPUS_STAGES = (
    "raw_comments",
    "population_submitted",
    "classified",
    "usable",
    "attributed",
)

# Which population each produced table draws from. None for the
# dimensions and reference tables, which hold no comments, and for
# corpus_daily, whose columns are each their own population.
TABLE_POPULATIONS: dict[str, str | None] = {
    "player_overall": "attributed",
    "player_temporal": "attributed",
    "player_fan_team": "attributed_flaired",
    "fan_team_overall": "flaired",
    "game_sentiment": "in_thread",
    "players": None,
    "teams": None,
    "games": None,
    "player_games": None,
    "posts": None,
    "comment_samples": "attributed",
    "corpus_daily": None,
}


class ClassifierIdentity(TypedDict):
    """One classifier stage's frozen identity, from its birth-certificate stamps."""

    model: str
    prompt_version: str
    prompt: str | None  # the template text, when the live stage still carries it


class SamplesRule(TypedDict):
    """How comment_samples are selected; the values are utils.constants."""

    top_n: int
    min_confidence: float  # polar rows only; neutral exempt
    max_body_chars: int
    requires_target: bool  # the classifier's named-pick gate; lifted when verified
    pool_k: int  # verifier candidate depth per cell
    admission: str  # "verified" (on the verifier's verdict) | "gate_only"


class ReceiptsFigures(TypedDict):
    """What the verifier measured; null in the gate-only fallback."""

    verified: bool
    coverage: float | None  # share of the current pool with a verdict
    precision: float | None  # affirmed share of the would-have-shipped top-n
    attribution_toward_share: float | None  # affirmed share, random named stratum


class GroupFigures(TypedDict):
    """One labeling group of the accuracy sample, unweighted."""

    size: int  # rows of the draw in the group
    weight: float  # share of the estimate; ordered carries the held-out rows' too
    labeled: int
    rejected: int  # ruled not a valid input
    scored: int  # labeled minus rejected
    sentiment_agreement: float | None
    target_agreement: float | None
    joint_agreement: float | None


class ClassAgreement(TypedDict):
    """One sentiment class of the accuracy sample: the classifier against manual review."""

    predicted: int  # scored rows the classifier gave this label
    labeled: int  # scored rows manual review gave this label
    precision: float | None  # labeled so, of the predicted; weighted
    recall: float | None  # predicted so, of the labeled; weighted
    toward_precision: float | None  # labeled so and about the attributed player


class ClassMix(TypedDict):
    """One sentiment class's share of the scored rows, each side's; weighted."""

    classifier: float | None
    manual: float | None
    gap: float | None  # classifier minus manual
    gap_margin: float | None  # half-width of the gap's 95% interval, paired by row


class AccuracyFigures(TypedDict):
    """The blind random sample's agreement figures; null until it is labeled.

    Every share weights the first pass and the ordered group by their
    sizes in the draw; a margin is the half-width of a 95% interval.
    """

    labeled: bool
    drawn: int | None  # rows in the sample
    scored: int | None  # labeled minus rejected, the estimating groups
    rejected: int | None  # ruled not a valid input, the estimating groups
    seed: int | None
    drawn_at: str | None
    rubric: str | None  # the labeling rubric's version
    groups: dict[str, GroupFigures] | None  # keyed by pipeline.accuracy.GROUPS
    sentiment_agreement: float | None  # label matches, of the comparable rows
    sentiment_margin: float | None
    target_agreement: float | None  # manual target is the attributed player, of polar
    target_margin: float | None
    joint_agreement: float | None  # label matches and, when polar, the target too
    joint_margin: float | None
    by_class: dict[str, ClassAgreement] | None  # keyed neg / neu / pos
    class_mix: dict[str, ClassMix] | None  # keyed neg / neu / pos
    context_share: float | None  # scored rows the thread decided
    unsure_share: float | None  # scored rows judged a coin flip
    reject_share: float | None  # labeled rows ruled not a valid input


class Floors(TypedDict):
    """Consumer-side minimum comment counts."""

    fanbase_min_n: int
    week_min_n: int
    belt_min_n: int
    game_min_n: int
    race_entry_min_n: int  # season-to-date, not per cell


class ReactionLag(TypedDict):
    """How long the room takes to react to a play, measured season-wide."""

    candidates: int  # tracked players' blocks, steals and made dunks
    anchors: int  # candidates whose reaction reached the floor
    games: int  # games with at least one anchor
    median_offset_seconds: int | None  # first reaction minus the play's timestamp
    p25_offset_seconds: int | None
    p75_offset_seconds: int | None


class RecapsRule(TypedDict):
    """How a recap keeps bodies and how the room's lag is measured; utils.constants."""

    room_bucket_seconds: int  # wall-clock bucket for the room's top-voted comments
    room_bodies_per_bucket: int  # non-focus bodies kept per bucket, by score
    anchor_window_seconds: int  # a play's reaction is looked for within this
    anchor_min_reactions: int  # comments naming the play in one minute to count
    anchor_vocabulary: dict[str, str]  # play kind -> the pattern naming it
    reaction_lag: ReactionLag


class Rules(TypedDict):
    """The semantic layer: every number a surface states about its method."""

    qualified_threshold: int
    samples: SamplesRule
    receipts: ReceiptsFigures
    accuracy: AccuracyFigures
    floors: Floors
    recaps: RecapsRule
    metrics: dict[str, str]  # METRIC_FORMULAS


class Corpus(TypedDict):
    """The funnel counts, keyed by CORPUS_STAGES; None where unrecorded."""

    raw_comments: int | None
    population_submitted: int | None
    classified: int
    usable: int
    attributed: int


class TableEntry(TypedDict):
    """One produced table: where it is, how big, and what it draws from."""

    file: str
    rows: int
    population: str | None  # a POPULATIONS key


class PeriodCounts(TypedDict):
    """Sentiment counts of the focus player's comments in one period."""

    neg: int
    pos: int
    neu: int


class RecapEntry(TypedDict):
    """One curated recap: where it is, how big, and the rollup the index draws."""

    file: str  # recap_file(key)
    rows: int  # the comments frame's height
    game_id: str
    attributed_player: str
    player_id: int
    slug: str
    live_n: int  # focus comments in the live threads
    room_n: int  # the whole room: posts.num_comments over the live threads
    by_period: dict[str, PeriodCounts]  # keyed by period; live and break comments
    swing: float  # negative share, last period minus first
    minutes_diff: int  # whole minutes the stints sit from the box score's
    population: str  # RECAP_POPULATION


class RecapHeader(TypedDict):
    """A recap file's scalar block: identity and lineage; the frames follow."""

    schema_version: int
    season: str
    generated_at: str
    game_id: str
    attributed_player: str
    player_id: int
    slug: str
    config_versions: dict[str, str]  # the configs a recap derives from
    classifiers: dict[str, ClassifierIdentity]  # the sentiment stage


class Manifest(TypedDict):
    """manifest.json: identity, rules, season facts, table and recap registries."""

    schema_version: int
    season: str
    generated_at: str  # the one field a rebuild changes; diff modulo it
    config_versions: dict[str, str]  # config name -> version, every registered config
    classifiers: dict[str, ClassifierIdentity]  # by stage; absent until stamped
    snapshots: dict[
        str, str | None
    ]  # games_fetched_at, posts/corpus_daily processed_at
    rules: Rules
    calendar: dict[str, str | None]  # season.yaml calendar, CALENDAR_KEYS
    corpus: Corpus
    populations: dict[str, str]  # POPULATIONS
    tables: dict[str, TableEntry]  # every DASHBOARD_OUTPUT_SCHEMAS table
    recaps: dict[str, RecapEntry]  # every curated recap, keyed game_id-slug


def load_manifest(path: Path) -> Manifest:
    """
    Read a manifest.json back as the typed contract.

    Checks presence of every Manifest block and of every field on each
    registry entry, not the values: the writer is the only producer, so
    a missing key means the wrong file or an older contract, and either
    should stop a reader before it trusts the registry.

    Args:
        path: Path to a manifest.json.

    Returns:
        The manifest, key order as written.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the document is not a JSON object, lacks any
            Manifest block, registers a table without every TableEntry
            field or a recap without every RecapEntry field, or names a
            file other than the table's or recap's own. The message
            names the path and the keys.
    """
    with open(path) as f:
        document = json.load(f)

    if not isinstance(document, dict):
        raise ValueError(f"{path}: manifest must be a JSON object")

    missing = [key for key in Manifest.__required_keys__ if key not in document]
    if missing:
        raise ValueError(f"{path} is missing manifest blocks: {sorted(missing)}")

    for name, entry in document["tables"].items():
        fields = [key for key in TableEntry.__required_keys__ if key not in entry]
        if fields:
            raise ValueError(
                f"{path}: table {name!r} is missing registry fields: {sorted(fields)}"
            )
        # The writer names files after their tables; a reader joins the
        # value to a directory and a key prefix, so nothing else is allowed
        if entry["file"] != f"{name}.parquet":
            raise ValueError(
                f"{path}: table {name!r} registers file {entry['file']!r}, "
                f"expected {name + '.parquet'!r}"
            )

    for key, entry in document["recaps"].items():
        fields = [k for k in RecapEntry.__required_keys__ if k not in entry]
        if fields:
            raise ValueError(
                f"{path}: recap {key!r} is missing registry fields: {sorted(fields)}"
            )
        # Same rule as the tables: the file is named by its key, under
        # the recaps directory, and nothing else
        if entry["file"] != recap_file(key):
            raise ValueError(
                f"{path}: recap {key!r} registers file {entry['file']!r}, "
                f"expected {recap_file(key)!r}"
            )

    return cast(Manifest, document)


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


def validate_nullability(df: pl.DataFrame, nullable: frozenset[str], name: str) -> None:
    """
    Fail if any column not declared nullable holds a null.

    The companion to validate_schema at the write boundary: names and
    dtypes there, null-freedom here. A column that legitimately holds
    nulls is declared in NULLABLE_COLUMNS, never patched around.

    Args:
        df: DataFrame to validate.
        nullable: The columns allowed to hold nulls (NULLABLE_COLUMNS[name]).
        name: Human-readable target name for error messages.

    Raises:
        ValueError: If an undeclared column holds nulls. The message names
            the target and every offending column with its null count.
    """
    null_counts = df.null_count().row(0, named=True)
    offending = {
        col: count
        for col, count in null_counts.items()
        if count > 0 and col not in nullable
    }
    if offending:
        detail = ", ".join(f"{col} ({count})" for col, count in offending.items())
        raise ValueError(
            f"Nullability validation failed for {name!r}: undeclared nulls in {detail}"
        )
