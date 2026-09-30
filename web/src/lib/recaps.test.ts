import { describe, expect, it } from 'vitest'

import type { GamesRow, Manifest, PeriodCounts, PlayerGamesRow, PlayersRow, RecapEntry, Tables } from '../data/types.gen'
import { boxLine, buildRecaps, countsLine, hook, lagPhrase, leadAndList, periodCells, periodsText, recapDelta, recapHrefs, recapTone } from './recaps'
import type { Counts } from './types'

const c = (neg: number, neu: number, pos: number): Counts => ({ neg, neu, pos, total: neg + neu + pos })

// Periods from negative shares out of 100 comments each, the rest neutral.
const periods = (...negs: number[]): Record<string, PeriodCounts> =>
  Object.fromEntries(negs.map((neg, i) => [String(i + 1), { neg, pos: 0, neu: 100 - neg }]))

describe('periodCells', () => {
  it('orders the periods numerically, labels overtime, and adds totals', () => {
    const cells = periodCells({ '5': { neg: 1, pos: 1, neu: 0 }, '1': { neg: 3, pos: 0, neu: 1 }, '2': { neg: 0, pos: 0, neu: 0 }, '3': { neg: 2, pos: 2, neu: 2 }, '4': { neg: 1, pos: 0, neu: 0 } })
    expect(cells.map((p) => p.label)).toEqual(['Q1', 'Q2', 'Q3', 'Q4', 'OT1'])
    expect(cells[0]!.counts).toEqual(c(3, 1, 0))
    expect(cells[1]!.counts.total).toBe(0)
  })

  it('reads as one line, a silent period named as such', () => {
    const cells = periodCells({ '1': { neg: 29, pos: 38, neu: 33 }, '2': { neg: 0, pos: 0, neu: 0 } })
    expect(periodsText(cells)).toBe('Q1 29% negative of 100, Q2 no comments')
  })
})

describe('hook', () => {
  const usual = 0.35

  it('reads a rise between a period and a later one', () => {
    expect(hook(periodCells(periods(29, 34, 50, 60)), usual)).toBe('29% negative in the 1st, 60% by the 4th.')
  })

  it('reads a fall the same way', () => {
    expect(hook(periodCells(periods(34, 33, 73, 22)), usual)).toBe('73% negative in the 3rd, 22% by the 4th.')
  })

  it('picks the largest move, not the first', () => {
    expect(hook(periodCells(periods(51, 34, 76, 80)), usual)).toBe('34% negative in the 2nd, 80% by the 4th.')
  })

  it('reads one period standing off agreeing neighbours as a spike', () => {
    expect(hook(periodCells(periods(30, 65, 32, 34)), usual)).toBe('Spiked to 65% negative in the 2nd, from 30% either side.')
    expect(hook(periodCells(periods(60, 20, 62, 61)), usual)).toBe('Dipped to 20% negative in the 2nd, from 60% either side.')
  })

  it('does not call it a spike when the neighbours disagree', () => {
    // 33 and 22 sit 11 points apart, past the return band, so the fall reads
    expect(hook(periodCells(periods(34, 33, 73, 22)), usual)).not.toMatch(/Spiked/)
  })

  it('reads a night hated from the tip against his usual', () => {
    expect(hook(periodCells(periods(83, 67, 78, 74)), 0.5)).toBe('83% negative from the tip, 33 points above his usual 50%.')
  })

  it('falls back to the range when nothing moved', () => {
    expect(hook(periodCells(periods(33, 41, 36, 38)), usual)).toBe('Held between 33% and 41% negative all night.')
  })

  it('prefers regulation and reads the overtimes only when regulation held no story', () => {
    expect(hook(periodCells(periods(10, 19, 6, 14, 50, 29)), usual)).toBe('6% negative in the 3rd, 50% by the 1st overtime.')
    expect(hook(periodCells(periods(35, 19, 38, 41, 60, 51)), usual)).toBe('19% negative in the 2nd, 41% by the 4th.')
  })

  it('skips a period nobody spoke in', () => {
    const by = periods(29, 34, 50, 60)
    by['2'] = { neg: 0, pos: 0, neu: 0 }
    expect(hook(periodCells(by), usual)).toBe('29% negative in the 1st, 60% by the 4th.')
    expect(hook(periodCells(periods(0, 0)), usual)).toBe('Held between 0% and 0% negative all night.')
  })
})

describe('the verdict against his usual', () => {
  const usual = c(40, 40, 20) // 40%

  it('is the night minus his usual at or above the floor, null under it', () => {
    expect(recapDelta(c(60, 20, 20), usual, 20)).toBeCloseTo(0.2)
    expect(recapDelta(c(2, 1, 1), usual, 20)).toBeNull()
    expect(recapDelta(null, usual, 20)).toBeNull()
  })

  it('tones heat harsher, ice kinder, bone otherwise', () => {
    expect(recapTone(0.2)).toBe('neg')
    expect(recapTone(-0.05)).toBe('pos')
    expect(recapTone(0)).toBe('neu')
    expect(recapTone(null)).toBe('neu')
  })
})

describe('the lines', () => {
  it('prints his line and the two counts', () => {
    expect(boxLine({ pts: 19, reb: 14, minutes: 38 } as PlayerGamesRow)).toBe('19 pts · 14 reb · 38 min')
    expect(countsLine({ live_n: 2166, room_n: 47934 } as RecapEntry)).toBe('2,166 comments about him in a 47,934-comment thread')
  })

  it('says the lag in words, never in seconds', () => {
    expect(lagPhrase(65)).toBe('about a minute')
    expect(lagPhrase(30)).toBe('under a minute')
    expect(lagPhrase(150)).toBe('about 3 minutes')
    expect(lagPhrase(null)).toBeNull()
  })
})

// --- The joins ---------------------------------------------------------------

const player = (name: string, id: number, slug: string): PlayersRow => ({
  attributed_player: name,
  slug,
  roster_team: 'Team One',
  conference: 'West',
  player_id: id,
  headshot_url: `https://media/${id}.png`,
  position: 'G',
  birth_date: null,
  experience: null,
  school: null,
  jersey_number: null,
  height: null,
  weight: null,
})

const game = (id: string, date: string, extra: Partial<GamesRow> = {}): GamesRow => ({
  game_id: id,
  game_date: date,
  season_type: 'playoffs',
  nba_cup_final: false,
  neutral_site: false,
  home_team: 'Team One',
  away_team: 'Team Two',
  home_score: 103,
  away_score: 111,
  winner: 'Team Two',
  playoff_round: 3,
  playoff_series: 1,
  playoff_game: 7,
  ...extra,
})

const box = (id: string, name: string, pid: number): PlayerGamesRow => ({
  game_id: id,
  attributed_player: name,
  player_id: pid,
  roster_team: 'Team One',
  opponent: 'Team Two',
  is_home: true,
  wl: 'L',
  minutes: 33,
  fgm: 1,
  fga: 8,
  fg3m: 0,
  fg3a: 3,
  ftm: 2,
  fta: 2,
  oreb: 1,
  dreb: 3,
  reb: 4,
  ast: 0,
  stl: 2,
  blk: 2,
  tov: 2,
  pf: 2,
  pts: 4,
  plus_minus: -3,
})

const entry = (id: string, name: string, pid: number, slug: string, byPeriod: Record<string, PeriodCounts>): RecapEntry => ({
  file: `recaps/${id}-${slug}.json`,
  rows: 1,
  game_id: id,
  attributed_player: name,
  player_id: pid,
  slug,
  live_n: 400,
  room_n: 9000,
  by_period: byPeriod,
  swing: 0,
  minutes_diff: 0,
  population: 'live_thread',
})

const rates = (neg: number, neu: number, pos: number) => {
  const total = neg + neu + pos
  return { neg_count: neg, neu_count: neu, pos_count: pos, comment_count: total, neg_rate: neg / total, pos_rate: pos / total, net_sentiment: (pos - neg) / total, polarization: (pos + neg) / total }
}

const TABLES = {
  players: [player('One Player', 1, 'one-player'), player('Two Player', 2, 'two-player')],
  teams: [
    { team: 'Team One', abbreviation: 'ONE', conference: 'West', team_id: 10, logo_url: '' },
    { team: 'Team Two', abbreviation: 'TWO', conference: 'West', team_id: 20, logo_url: '' },
  ],
  games: [game('g7', '2026-05-30'), game('g1', '2025-10-21', { season_type: 'regular_season', playoff_round: null, playoff_series: null, playoff_game: null })],
  player_games: [box('g7', 'One Player', 1), box('g1', 'Two Player', 2)],
  game_sentiment: [{ attributed_player: 'One Player', player_id: 1, game_id: 'g7', ...rates(60, 20, 20), thread_comment_count: 1 }],
  player_overall: [
    { attributed_player: 'One Player', player_id: 1, ...rates(50, 30, 20) },
    { attributed_player: 'Two Player', player_id: 2, ...rates(30, 40, 30) },
  ],
} as unknown as Tables

const MANIFEST = {
  rules: { floors: { game_min_n: 20 } },
  recaps: {
    'g7-one-player': entry('g7', 'One Player', 1, 'one-player', periods(83, 67, 78, 74)),
    'g1-two-player': entry('g1', 'Two Player', 2, 'two-player', periods(29, 34, 50, 60)),
  },
} as unknown as Manifest

describe('buildRecaps', () => {
  const recaps = buildRecaps(MANIFEST, TABLES)

  it('joins every entry in registry order', () => {
    expect(recaps.map((r) => r.key)).toEqual(['g7-one-player', 'g1-two-player'])
    expect(recaps[0]!.line.text).toBe('West Finals · Game 7 · TWO 111 @ ONE 103 · May 30')
    expect(recaps[1]!.line.text).toBe('Regular season · TWO 111 @ ONE 103 · Oct 21')
    expect(recaps[0]!.player.slug).toBe('one-player')
    expect(recaps[0]!.box.pts).toBe(4)
  })

  it('computes the hook against his usual and the strip over the periods', () => {
    expect(recaps[0]!.hook).toBe('83% negative from the tip, 33 points above his usual 50%.')
    expect(recaps[0]!.inPeriods).toEqual(c(302, 98, 0))
    expect(recaps[1]!.hook).toBe('29% negative in the 1st, 60% by the 4th.')
  })

  it('judges the night against his usual where the view has a row, and leaves it null otherwise', () => {
    expect(recaps[0]!.night).toEqual(c(60, 20, 20))
    expect(recaps[0]!.delta).toBeCloseTo(0.6 - 0.5)
    expect(recaps[0]!.tone).toBe('neg')
    expect(recaps[1]).toMatchObject({ night: null, delta: null, tone: 'neu' })
  })

  it('splits the lead from the list', () => {
    expect(leadAndList(recaps).lead?.key).toBe('g7-one-player')
    expect(leadAndList(recaps).list.map((r) => r.key)).toEqual(['g1-two-player'])
    expect(leadAndList([])).toEqual({ lead: null, list: [] })
  })

  it('throws with the key when an entry does not join', () => {
    const broken = { ...MANIFEST, recaps: { 'g9-one-player': entry('g9', 'One Player', 1, 'one-player', periods(1)) } } as Manifest
    expect(() => buildRecaps(broken, TABLES)).toThrow('recap g9-one-player: the registry entry does not join')
  })
})

describe('recapHrefs', () => {
  it("maps one player's recap games to their routes", () => {
    expect(recapHrefs(MANIFEST.recaps, 'One Player')).toEqual(new Map([['g7', '/recaps/g7-one-player/']]))
    expect(recapHrefs(MANIFEST.recaps, 'Nobody').size).toBe(0)
  })
})
