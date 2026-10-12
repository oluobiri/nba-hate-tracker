// Row builders for the season tests: one row per table the page reads, every
// column defaulted, overrides on top; a toy calendar shaped like 2025-26.
// Test-only; nothing ships it.
import type { CorpusDailyRow, GameSentimentRow, GamesRow, PlayerGamesRow, PlayerRoomRow, PlayerTemporalRow, PlayersRow, PostsRow, RoomTemporalRow, TeamsRow } from '../data/types.gen'
import type { Calendar } from './weeks'

export const CAL: Calendar = {
  opening_night: '2025-10-21',
  nba_cup_final: '2025-12-16',
  christmas: '2025-12-25',
  trade_deadline: '2026-02-05',
  all_star_weekend: '2026-02-13',
  all_star: '2026-02-15',
  play_in_start: '2026-04-14',
  play_in_end: '2026-04-17',
  playoffs_start: '2026-04-18',
  finals_start: '2026-06-03',
  finals_end: '2026-06-13',
  draft: '2026-06-23',
}

const DAY_MS = 86_400_000
export const plusDays = (iso: string, n: number): string => new Date(Date.parse(iso) + n * DAY_MS).toISOString().slice(0, 10)

const metrics = (neg: number, neu: number, pos: number) => {
  const total = neg + neu + pos
  return {
    neg_count: neg,
    neu_count: neu,
    pos_count: pos,
    comment_count: total,
    neg_rate: total ? neg / total : 0,
    pos_rate: total ? pos / total : 0,
    net_sentiment: total ? (pos - neg) / total : 0,
    polarization: total ? (pos + neg) / total : 0,
  }
}

export const daily = (day: string, neg: number, neu: number, pos: number): CorpusDailyRow => ({
  day,
  raw_comments: (neg + neu + pos) * 4,
  population_submitted: (neg + neu + pos) * 2,
  usable: (neg + neu + pos) * 2,
  attributed: neg + neu + pos,
  neg_count: neg,
  neu_count: neu,
  pos_count: pos,
})

/** Consecutive nights from `start`, one triple of counts each. */
export const nightsFrom = (start: string, triples: readonly [number, number, number][]): CorpusDailyRow[] => triples.map(([neg, neu, pos], i) => daily(plusDays(start, i), neg, neu, pos))

export const game = (id: string, date: string, o: Partial<GamesRow> = {}): GamesRow => ({
  game_id: id,
  game_date: date,
  season_type: 'regular_season',
  nba_cup_final: false,
  neutral_site: false,
  home_team: 'Oklahoma City Thunder',
  away_team: 'San Antonio Spurs',
  home_score: 100,
  away_score: 110,
  winner: 'San Antonio Spurs',
  playoff_round: null,
  playoff_series: null,
  playoff_game: null,
  ...o,
})

export const team = (name: string, abbreviation: string, conference = 'West'): TeamsRow => ({ team: name, abbreviation, conference, team_id: abbreviation.length, logo_url: '' })

export const TEAMS: TeamsRow[] = [team('Oklahoma City Thunder', 'OKC'), team('San Antonio Spurs', 'SAS'), team('New York Knicks', 'NYK', 'East'), team('Dallas Mavericks', 'DAL')]

export const player = (name: string, o: Partial<PlayersRow> = {}): PlayersRow => ({
  attributed_player: name,
  slug: name.toLowerCase().replace(/[^a-z]+/g, '-'),
  roster_team: 'San Antonio Spurs',
  conference: 'West',
  player_id: name.length,
  headshot_url: '',
  position: 'F',
  birth_date: null,
  experience: null,
  school: null,
  jersey_number: null,
  height: null,
  weight: null,
  ...o,
})

export const sentiment = (name: string, gameId: string, neg: number, neu: number, pos: number): GameSentimentRow => ({
  attributed_player: name,
  player_id: name.length,
  game_id: gameId,
  ...metrics(neg, neu, pos),
  thread_comment_count: (neg + neu + pos) * 2,
})

export const post = (gameId: string | null, postType: string, numComments: number, o: Partial<PostsRow> = {}): PostsRow => ({
  post_id: `t3_${gameId ?? 'x'}_${postType}`,
  title: 'Game Thread',
  created_utc: 1,
  score: 1,
  num_comments: numComments,
  link_flair_text: null,
  post_type: postType,
  source: null,
  game_id: gameId,
  is_primary: true,
  ...o,
})

export const roomWeek = (postType: string, week: string, neg: number, neu: number, pos: number): RoomTemporalRow => ({ post_type: postType, week: `${week}T00:00:00`, ...metrics(neg, neu, pos) })

export const playerRoom = (name: string, postType: string, neg: number, neu: number, pos: number): PlayerRoomRow => ({ attributed_player: name, player_id: name.length, post_type: postType, ...metrics(neg, neu, pos) })

export const temporal = (name: string, week: string, neg: number, neu: number, pos: number): PlayerTemporalRow => ({ attributed_player: name, player_id: name.length, week: `${week}T00:00:00`, ...metrics(neg, neu, pos) })

export const playerGame = (name: string, gameId: string, o: Partial<PlayerGamesRow> = {}): PlayerGamesRow => ({
  game_id: gameId,
  attributed_player: name,
  player_id: name.length,
  roster_team: 'San Antonio Spurs',
  opponent: 'Oklahoma City Thunder',
  is_home: false,
  wl: 'W',
  minutes: 30,
  fgm: 5,
  fga: 10,
  fg3m: 1,
  fg3a: 3,
  ftm: 2,
  fta: 2,
  oreb: 1,
  dreb: 4,
  reb: 5,
  ast: 3,
  stl: 1,
  blk: 0,
  tov: 2,
  pf: 2,
  pts: 13,
  plus_minus: 4,
  ...o,
})
