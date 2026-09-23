import { describe, expect, it } from 'vitest'

import type { GameSentimentRow, GamesRow, PlayerGamesRow } from '../data/types.gen'
import { buildGameLog, gamesSummary, neverDressedSentence, scatterLead, scatterPoints, seasonAverages, talkedThreads, weekGames, winLossSplit } from './games'
import { negRate } from './metrics'
import type { Counts } from './types'

const c = (neg: number, neu: number, pos: number): Counts => ({ neg, neu, pos, total: neg + neu + pos })

const game = (id: string, date: string, home: string, away: string, hs: number, as: number, extra: Partial<GamesRow> = {}): GamesRow => ({
  game_id: id,
  game_date: date,
  season_type: 'regular_season',
  nba_cup_final: false,
  neutral_site: false,
  home_team: home,
  away_team: away,
  home_score: hs,
  away_score: as,
  winner: hs > as ? home : away,
  playoff_round: null,
  playoff_series: null,
  playoff_game: null,
  ...extra,
})

const line = (id: string, opponent: string, isHome: boolean | null, wl: string, box: Partial<PlayerGamesRow> = {}): PlayerGamesRow => ({
  game_id: id,
  attributed_player: 'Leader',
  player_id: 1,
  roster_team: 'Boston Celtics',
  opponent,
  is_home: isHome,
  wl,
  minutes: 34,
  fgm: 11,
  fga: 20,
  fg3m: 2,
  fg3a: 6,
  ftm: 6,
  fta: 8,
  oreb: 2,
  dreb: 8,
  reb: 10,
  ast: 7,
  stl: 1,
  blk: 1,
  tov: 4,
  pf: 3,
  pts: 30,
  plus_minus: 8,
  ...box,
})

const room = (id: string, neg: number, neu: number, pos: number): GameSentimentRow => ({
  attributed_player: 'Leader',
  player_id: 1,
  game_id: id,
  neg_count: neg,
  pos_count: pos,
  neu_count: neu,
  comment_count: neg + neu + pos,
  neg_rate: 0,
  pos_rate: 0,
  net_sentiment: 0,
  polarization: 0,
  thread_comment_count: 999,
})

const GAMES = new Map(
  [
    game('g1', '2025-10-22', 'Boston Celtics', 'New York Knicks', 112, 98),
    game('g2', '2025-10-24', 'Miami Heat', 'Boston Celtics', 105, 101),
    game('g3', '2025-10-29', 'Boston Celtics', 'Utah Jazz', 120, 90),
    game('g4', '2025-11-01', 'Boston Celtics', 'Denver Nuggets', 99, 110, { neutral_site: true }),
  ].map((g) => [g.game_id, g]),
)
const ABBR = new Map([
  ['New York Knicks', 'NYK'],
  ['Miami Heat', 'MIA'],
  ['Utah Jazz', 'UTA'],
  ['Denver Nuggets', 'DEN'],
])
const LINES = [
  line('g1', 'New York Knicks', true, 'W'),
  line('g2', 'Miami Heat', false, 'L'),
  line('g3', 'Utah Jazz', true, 'W', { minutes: 0, pts: 0, fgm: 0, fga: 0, ftm: 0, fta: 0, oreb: 0, dreb: 0, reb: 0, ast: 0, stl: 0, blk: 0, tov: 0, pf: 0, plus_minus: 0 }),
  line('g4', 'Denver Nuggets', null, 'L'),
]
// g1 talked (60% neg), g2 talked (20% neg), g3 talked but DNP, g4 under the floor; g9 undressed.
const ROOM = [room('g1', 30, 10, 10), room('g2', 5, 15, 5), room('g3', 20, 0, 0), room('g4', 3, 1, 1), room('g9', 50, 0, 0)]
const BASELINE = c(40, 40, 20) // 40%
const FLOOR = 10

describe('buildGameLog', () => {
  const log = buildGameLog(LINES, ROOM, GAMES, ABBR, BASELINE, FLOOR)

  it('keeps every dressed game in date order and drops game threads he did not dress for', () => {
    expect(log.map((g) => g.gameId)).toEqual(['g1', 'g2', 'g3', 'g4'])
  })

  it('prints his score first, the opponent abbreviation and the box line', () => {
    expect(log[0]).toMatchObject({ score: '112–98', opponentAbbr: 'NYK', home: true, win: true, line: '30 pts · 10 reb · 7 ast' })
    expect(log[1]).toMatchObject({ score: '101–105', home: false, win: false })
    expect(log[3]).toMatchObject({ score: '99–110', home: null })
  })

  it('judges a talked game against the baseline and leaves the rest null', () => {
    expect(log[0]!.talked).toBe(true)
    expect(log[0]!.delta).toBeCloseTo(0.6 - 0.4)
    expect(log[1]!.delta).toBeCloseTo(0.2 - 0.4)
    expect(log[3]).toMatchObject({ talked: false, delta: null })
    expect(log[3]!.counts).toEqual(c(3, 1, 1))
  })

  it('marks a dressed game with no minutes as DNP, still in the log', () => {
    expect(log[2]).toMatchObject({ dnp: true, line: 'DNP', gameScore: 0, talked: true })
  })

  it('scores a played game by Game Score', () => {
    expect(log[0]!.gameScore).toBeCloseTo(24.8)
  })
})

describe('winLossSplit', () => {
  const log = buildGameLog(LINES, ROOM, GAMES, ABBR, BASELINE, FLOOR)

  it('sums counts of graded games per side, leaving out DNP and under-floor games', () => {
    const { wins, losses } = winLossSplit(log, FLOOR)
    expect(wins).toEqual(c(30, 10, 10)) // g1 only: g3 was a DNP win
    expect(losses).toEqual(c(5, 15, 5)) // g2 only: g4 under the floor
  })

  it('nulls a side that does not reach the floor', () => {
    expect(winLossSplit(log, 30).losses).toBeNull()
    expect(winLossSplit(log, 30).wins).toEqual(c(30, 10, 10))
  })
})

describe('scatterPoints', () => {
  it('plots graded games only, with a readable label', () => {
    const pts = scatterPoints(buildGameLog(LINES, ROOM, GAMES, ABBR, BASELINE, FLOOR))
    expect(pts.map((p) => p.gameId)).toEqual(['g1', 'g2'])
    expect(pts[0]).toMatchObject({ win: true, y: 0.6 })
    expect(pts[0]!.x).toBeCloseTo(24.8)
    expect(pts[1]!.label).toBe('L @ MIA 101–105: Game Score 24.8, 20% negative')
  })
})

describe('scatterLead', () => {
  it('reads the sign and size of r into plain words', () => {
    expect(scatterLead('Leader', 40, -0.45)).toMatch(/^Bad nights get punished: across 40 games/)
    expect(scatterLead('Leader', 40, -0.2)).toMatch(/^Bad nights get punished, mildly/)
    expect(scatterLead('Leader', 40, 0.02)).toMatch(/^The room barely grades the box score/)
    expect(scatterLead('Leader', 40, 0.2)).toMatch(/^Good nights get punished, mildly/)
    expect(scatterLead('Leader', 40, 0.5)).toMatch(/^Good nights get punished: /)
    expect(scatterLead('Leader', 2, null)).toBe("Too few games to say whether the room grades Leader's box score.")
  })
})

describe('never dressed', () => {
  it('counts the game threads at the floor and says so', () => {
    expect(talkedThreads(ROOM, FLOOR)).toBe(4)
    expect(neverDressedSentence('Ghost', 4, FLOOR)).toBe(
      'Ghost never dressed this season; the room still talked about him in 4 game threads with at least 10 comments each.',
    )
  })
})

describe('gamesSummary', () => {
  const log = buildGameLog(LINES, ROOM, GAMES, ABBR, BASELINE, FLOOR)

  it('states the graded count and the loss/win split against the baseline', () => {
    expect(gamesSummary('Leader', log, BASELINE, FLOOR)).toBe(
      'The room talked about Leader in 3 of his 4 games, at least 10 comments each. It was kinder after losses: 20% negative in losses against 60% in wins, on a season baseline of 40%.',
    )
  })

  it('says when one side is too thin', () => {
    const thin = buildGameLog(LINES, ROOM, GAMES, ABBR, BASELINE, 30)
    expect(gamesSummary('Leader', thin, BASELINE, 30)).toBe(
      'The room talked about Leader in 1 of his 4 games, at least 30 comments each. Too few graded games on one side to split wins from losses.',
    )
  })
})

describe('weekGames', () => {
  it('buckets the log by spine week', () => {
    const log = buildGameLog(LINES, ROOM, GAMES, ABBR, BASELINE, FLOOR)
    const spine = ['2025-10-20T00:00:00', '2025-10-27T00:00:00', '2025-11-03T00:00:00']
    const weeks = weekGames(log, spine)
    expect(weeks.map((w) => w.map((g) => g.gameId))).toEqual([['g1', 'g2'], ['g3', 'g4'], []])
    expect(negRate(weeks[0]![0]!.counts!)).toBeCloseTo(0.6)
  })
})

describe('seasonAverages', () => {
  it('averages regular-season games he played, leaving out DNP and the postseason', () => {
    const log = buildGameLog(LINES, ROOM, GAMES, ABBR, BASELINE, FLOOR)
    // g1, g2, g4 played (g3 DNP), all regular season: 30 pts, 10 reb, 7 ast each.
    expect(seasonAverages(log)).toEqual({ gp: 3, ppg: 30, rpg: 10, apg: 7 })
    expect(seasonAverages(log.map((g) => ({ ...g, seasonType: 'playoffs' })))).toBeNull()
  })
})
