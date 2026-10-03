// GENERATED from src/data/schema.json (schema_version 9) by scripts/codegen.ts.
// Do not edit: run `npm run codegen`. The build fails when this file is stale.

/** One row of player_overall.parquet. */
export interface PlayerOverallRow {
  attributed_player: string
  player_id: number
  neg_count: number
  pos_count: number
  neu_count: number
  comment_count: number
  neg_rate: number
  pos_rate: number
  net_sentiment: number
  polarization: number
}

/** One row of player_temporal.parquet. */
export interface PlayerTemporalRow {
  attributed_player: string
  player_id: number
  week: string
  neg_count: number
  pos_count: number
  neu_count: number
  comment_count: number
  neg_rate: number
  pos_rate: number
  net_sentiment: number
  polarization: number
}

/** One row of player_fan_team.parquet. */
export interface PlayerFanTeamRow {
  attributed_player: string
  player_id: number
  fan_team: string
  neg_count: number
  pos_count: number
  neu_count: number
  comment_count: number
  neg_rate: number
  pos_rate: number
  net_sentiment: number
  polarization: number
}

/** One row of fan_team_overall.parquet. */
export interface FanTeamOverallRow {
  fan_team: string
  neg_count: number
  pos_count: number
  neu_count: number
  comment_count: number
  neg_rate: number
  pos_rate: number
  net_sentiment: number
  polarization: number
  abbreviation: string
  conference: string
  logo_url: string
}

/** One row of game_sentiment.parquet. */
export interface GameSentimentRow {
  attributed_player: string
  player_id: number
  game_id: string
  neg_count: number
  pos_count: number
  neu_count: number
  comment_count: number
  neg_rate: number
  pos_rate: number
  net_sentiment: number
  polarization: number
  thread_comment_count: number
}

/** One row of players.parquet. */
export interface PlayersRow {
  attributed_player: string
  slug: string
  roster_team: string | null
  conference: string | null
  player_id: number
  headshot_url: string
  position: string | null
  birth_date: string | null
  experience: string | null
  school: string | null
  jersey_number: string | null
  height: string | null
  weight: string | null
}

/** One row of teams.parquet. */
export interface TeamsRow {
  team: string
  abbreviation: string
  conference: string
  team_id: number
  logo_url: string
}

/** One row of games.parquet. */
export interface GamesRow {
  game_id: string
  game_date: string
  season_type: string
  nba_cup_final: boolean
  neutral_site: boolean
  home_team: string
  away_team: string
  home_score: number
  away_score: number
  winner: string
  playoff_round: number | null
  playoff_series: number | null
  playoff_game: number | null
}

/** One row of player_games.parquet. */
export interface PlayerGamesRow {
  game_id: string
  attributed_player: string
  player_id: number
  roster_team: string
  opponent: string
  is_home: boolean | null
  wl: string
  minutes: number
  fgm: number
  fga: number
  fg3m: number
  fg3a: number
  ftm: number
  fta: number
  oreb: number
  dreb: number
  reb: number
  ast: number
  stl: number
  blk: number
  tov: number
  pf: number
  pts: number
  plus_minus: number
}

/** One row of posts.parquet. */
export interface PostsRow {
  post_id: string
  title: string
  created_utc: number
  score: number
  num_comments: number
  link_flair_text: string | null
  post_type: string
  source: string | null
  game_id: string | null
  is_primary: boolean
}

/** One row of comment_samples.parquet. */
export interface CommentSamplesRow {
  attributed_player: string
  player_id: number
  sentiment: string
  rank: number
  comment_id: string
  link_id: string
  body: string
  score: number
  created_utc: number
  fan_team: string | null
}

/** One row of corpus_daily.parquet. */
export interface CorpusDailyRow {
  day: string
  raw_comments: number
  population_submitted: number
  usable: number
  attributed: number | null
}

export type TableName = "player_overall" | "player_temporal" | "player_fan_team" | "fan_team_overall" | "game_sentiment" | "players" | "teams" | "games" | "player_games" | "posts" | "comment_samples" | "corpus_daily"

export interface Tables {
  player_overall: PlayerOverallRow[]
  player_temporal: PlayerTemporalRow[]
  player_fan_team: PlayerFanTeamRow[]
  fan_team_overall: FanTeamOverallRow[]
  game_sentiment: GameSentimentRow[]
  players: PlayersRow[]
  teams: TeamsRow[]
  games: GamesRow[]
  player_games: PlayerGamesRow[]
  posts: PostsRow[]
  comment_samples: CommentSamplesRow[]
  corpus_daily: CorpusDailyRow[]
}

export interface Manifest {
  schema_version: number
  season: string
  generated_at: string
  config_versions: Record<string, string>
  classifiers: Record<string, ClassifierIdentity>
  snapshots: Record<string, string | null>
  rules: Rules
  calendar: Record<string, string | null>
  corpus: Corpus
  populations: Record<string, string>
  tables: Record<string, TableEntry>
  recaps: Record<string, RecapEntry>
}

export interface ClassifierIdentity {
  model: string
  prompt_version: string
}

export interface Rules {
  qualified_threshold: number
  samples: SamplesRule
  receipts: ReceiptsFigures
  floors: Floors
  recaps: RecapsRule
  metrics: Record<string, string>
}

export interface SamplesRule {
  top_n: number
  min_confidence: number
  max_body_chars: number
  requires_target: boolean
  pool_k: number
  admission: string
}

export interface ReceiptsFigures {
  verified: boolean
  coverage: number | null
  precision: number | null
  attribution_toward_share: number | null
}

export interface Floors {
  fanbase_min_n: number
  week_min_n: number
  belt_min_n: number
  game_min_n: number
}

export interface RecapsRule {
  room_bucket_seconds: number
  room_bodies_per_bucket: number
  anchor_window_seconds: number
  anchor_min_reactions: number
  anchor_vocabulary: Record<string, string>
  reaction_lag: ReactionLag
}

export interface ReactionLag {
  candidates: number
  anchors: number
  games: number
  median_offset_seconds: number | null
  p25_offset_seconds: number | null
  p75_offset_seconds: number | null
}

export interface Corpus {
  raw_comments: number | null
  population_submitted: number | null
  classified: number
  usable: number
  attributed: number
}

export interface TableEntry {
  file: string
  rows: number
  population: string | null
}

export interface RecapEntry {
  file: string
  rows: number
  game_id: string
  attributed_player: string
  player_id: number
  slug: string
  live_n: number
  room_n: number
  by_period: Record<string, PeriodCounts>
  swing: number
  minutes_diff: number
  population: string
}

export interface PeriodCounts {
  neg: number
  pos: number
  neu: number
}

/** A frame as a document carries it: one array per column. */
export type Columnar<T> = { [K in keyof T]: T[K][] }

export interface RecapHeader {
  schema_version: number
  season: string
  generated_at: string
  game_id: string
  attributed_player: string
  player_id: number
  slug: string
  config_versions: Record<string, string>
  classifiers: Record<string, ClassifierIdentity>
}

/** One row of the recap document's periods frame. */
export interface RecapPeriodsRow {
  period: number
  start_seconds: number
  end_seconds: number
  start_wall: number
  end_wall: number
  start_action_number: number
  end_action_number: number
}

/** One row of the recap document's threads frame. */
export interface RecapThreadsRow {
  post_id: string
  is_primary: boolean
  created_utc: number
  num_comments: number
  comment_n: number
}

/** One row of the recap document's stints frame. */
export interface RecapStintsRow {
  person_id: number
  team_tricode: string
  period: number
  start_seconds: number
  end_seconds: number
}

/** One row of the recap document's plays frame. */
export interface RecapPlaysRow {
  action_number: number
  paired_action_number: number | null
  period: number
  clock: string
  game_seconds: number
  wall_clock: number
  kind: string
  action_type: string
  sub_type: string
  description: string
  team_tricode: string | null
  person_id: number
  player_name_i: string | null
  assist_person_id: number | null
  is_focus: boolean
  made: boolean | null
  shot_value: number
  x: number | null
  y: number | null
  shot_distance: number | null
  score_home: number
  score_away: number
}

/** One row of the recap document's comments frame. */
export interface RecapCommentsRow {
  comment_id: string
  post_id: string
  created_utc: number
  game_seconds: number
  phase: string
  sentiment: string
  score: number
  fan_team: string | null
  player_id: number | null
  is_focus: boolean
  body: string | null
}

export type RecapFrameName = "periods" | "threads" | "stints" | "plays" | "comments"

/** The recap document as published: its header and its frames as column arrays. */
export interface RecapDocument {
  header: RecapHeader
  frames: {
    periods: Columnar<RecapPeriodsRow>
    threads: Columnar<RecapThreadsRow>
    stints: Columnar<RecapStintsRow>
    plays: Columnar<RecapPlaysRow>
    comments: Columnar<RecapCommentsRow>
  }
}

/** The recap document's frames as rows. */
export interface RecapRows {
  periods: RecapPeriodsRow[]
  threads: RecapThreadsRow[]
  stints: RecapStintsRow[]
  plays: RecapPlaysRow[]
  comments: RecapCommentsRow[]
}
