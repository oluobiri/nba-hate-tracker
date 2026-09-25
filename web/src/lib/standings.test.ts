import { describe, expect, it } from 'vitest'

import type { FanTeamOverallRow, PlayerOverallRow, PlayersRow } from '../data/types.gen'
import { fanbaseStandings, playerStandings, rankIn } from './standings'

const player = (name: string): PlayersRow => ({
  attributed_player: name,
  slug: name.toLowerCase(),
  roster_team: null,
  conference: null,
  player_id: 1,
  headshot_url: `https://example.test/media/headshots/${name}.png`,
  position: null,
  birth_date: null,
  experience: null,
  school: null,
  jersey_number: null,
  height: null,
  weight: null,
})

const overall = (name: string, neg: number, neu: number, pos: number): PlayerOverallRow => ({
  attributed_player: name,
  player_id: 1,
  neg_count: neg,
  neu_count: neu,
  pos_count: pos,
  comment_count: neg + neu + pos,
  neg_rate: 0,
  pos_rate: 0,
  net_sentiment: 0,
  polarization: 0,
})

const fans = (team: string, neg: number, neu: number, pos: number): FanTeamOverallRow => ({
  fan_team: team,
  neg_count: neg,
  neu_count: neu,
  pos_count: pos,
  comment_count: neg + neu + pos,
  neg_rate: 0,
  pos_rate: 0,
  net_sentiment: 0,
  polarization: 0,
  abbreviation: team.slice(0, 3).toUpperCase(),
  conference: 'East',
  logo_url: `https://example.test/media/logos/${team}.svg`,
})

// Two official players, one under the minimum, one tracked player with no comments.
const OFFICIAL = 100
const TABLES = {
  players: [player('Harsh'), player('Mild'), player('Tiny'), player('Silent')],
  player_overall: [overall('Harsh', 60, 30, 10), overall('Mild', 20, 60, 20), overall('Tiny', 9, 1, 0)],
}

describe('playerStandings', () => {
  const s = playerStandings(TABLES, OFFICIAL)

  it('numbers the official board at the minimum and everyone on the all-players board', () => {
    expect(s.rankings.neg.map((r) => [r.row.name, r.rank])).toEqual([
      ['Tiny', null],
      ['Harsh', 1],
      ['Mild', 2],
    ])
    expect(s.allRankings.neg.map((r) => [r.row.name, r.rank])).toEqual([
      ['Tiny', 1],
      ['Harsh', 2],
      ['Mild', 3],
    ])
  })

  it('sums the league from official players only', () => {
    expect(s.league).toEqual({ neg: 80, neu: 90, pos: 30, total: 200 })
  })

  it('builds a verdict input per tracked player, ranks null below the minimum', () => {
    expect(s.inputs.get('Harsh')).toMatchObject({ counts: { total: 100 }, official: OFFICIAL, ranks: { neg: 1 }, allRanks: { neg: 2 }, tracked: 3 })
    expect(s.inputs.get('Tiny')).toMatchObject({ ranks: { neg: null }, allRanks: { neg: 1 } })
  })

  it('gives a player with no comments zero counts and the last all-players rank', () => {
    expect(s.inputs.get('Silent')).toMatchObject({ counts: { neg: 0, neu: 0, pos: 0, total: 0 }, ranks: { neg: null }, allRanks: { neg: 3 } })
  })

  it('rankIn reads a rank off a board, null when absent', () => {
    expect(rankIn(s.rankings.neg, 'Mild')).toBe(2)
    expect(rankIn(s.rankings.neg, 'Nobody')).toBeNull()
  })
})

describe('fanbaseStandings', () => {
  it('ranks every fanbase by negative rate, the saltiest first', () => {
    const ranked = fanbaseStandings([fans('Calm', 10, 80, 10), fans('Salty', 60, 30, 10)])
    expect(ranked.map((r) => [r.row.team.fan_team, r.rank])).toEqual([
      ['Salty', 1],
      ['Calm', 2],
    ])
    expect(ranked[0]!.row).toMatchObject({ neg: 60, total: 100 })
  })
})
