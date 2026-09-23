import { describe, expect, it } from 'vitest'

import { annotate, heroSentence, type Named, playerVerdict, rankChips } from './annotate'
import { rankBy } from './metrics'

const row = (name: string, neg: number, neu: number, pos: number): Named => ({ name, neg, neu, pos, total: neg + neu + pos })

// Harden-shaped leader, Wembanyama-shaped loudest, one row under the floor.
const ROWS = [row('Leader', 550, 300, 150), row('Loudest', 900, 1_500, 600), row('Tiny', 9, 1, 0)]
const OFFICIAL = 1_000

describe('annotate', () => {
  it('names the leader by rate and the loudest player with his rank, in the neg lens', () => {
    const out = annotate({ ranked: rankBy(ROWS, 'neg', OFFICIAL), lens: 'neg', threshold: OFFICIAL, official: OFFICIAL })
    expect(out).toHaveLength(2)
    expect(out[0]).toBe('Rates, not volume: 55.0% of the 1,000 comments about Leader are negative.')
    expect(out[1]).toBe('The most discussed player, Loudest, draws 3.0× the comments at 30.0% negative and ranks 2nd here.')
  })

  it('says so when the leader is also the loudest', () => {
    const rows = [row('Both', 600, 300, 100), row('Other', 100, 100, 100)]
    const out = annotate({ ranked: rankBy(rows, 'neg', 300), lens: 'neg', threshold: 300, official: 300 })
    expect(out[1]).toBe('Both is also the most discussed player on the board.')
  })

  it('states that volume is not hate and gives the negative-rate rank, in the volume lens', () => {
    const out = annotate({ ranked: rankBy(ROWS, 'volume', OFFICIAL), lens: 'volume', threshold: OFFICIAL, official: OFFICIAL })
    expect(out).toEqual([
      'Volume is not hate: Loudest is the most discussed player at 3,000 comments, 30.0% of them negative, which ranks 2nd by negative rate.',
    ])
  })

  it('defines polarization and prints both sides', () => {
    const out = annotate({ ranked: rankBy(ROWS, 'polar', OFFICIAL), lens: 'polar', threshold: OFFICIAL, official: OFFICIAL })
    expect(out[0]).toMatch(/take a side/)
    expect(out[1]).toBe('Leader leads at 70.0%: 55.0% negative, 15.0% positive.')
  })

  it('appends the unofficial note below the official minimum, counting hollow ranks', () => {
    const out = annotate({ ranked: rankBy(ROWS, 'neg', 10), lens: 'neg', threshold: 10, official: OFFICIAL })
    expect(out.at(-1)).toBe(
      'Unofficial view: minimum 10 comments. 1 of the 3 ranked players sits below the official minimum of 1,000; its rank is drawn hollow.',
    )
  })

  it('appends the custom note above the official minimum', () => {
    const out = annotate({ ranked: rankBy(ROWS, 'neg', 2_000), lens: 'neg', threshold: 2_000, official: OFFICIAL })
    expect(out.at(-1)).toBe('Custom view: minimum 2,000 comments, above the official 1,000. 1 player qualifies.')
  })

  it('handles a view nobody reaches', () => {
    const out = annotate({ ranked: rankBy(ROWS, 'neg', 99_999), lens: 'neg', threshold: 99_999, official: OFFICIAL })
    expect(out[0]).toBe('No player reaches this minimum.')
  })
})

describe('heroSentence', () => {
  it('rewrites per lens', () => {
    const base = { threshold: OFFICIAL, official: OFFICIAL }
    expect(heroSentence({ ranked: rankBy(ROWS, 'neg', OFFICIAL), lens: 'neg', ...base })).toBe("r/NBA's most hated player is Leader.")
    expect(heroSentence({ ranked: rankBy(ROWS, 'volume', OFFICIAL), lens: 'volume', ...base })).toBe("r/NBA's most discussed player is Loudest.")
  })

  it('marks a custom threshold as unofficial', () => {
    expect(heroSentence({ ranked: rankBy(ROWS, 'neg', 10), lens: 'neg', threshold: 10, official: OFFICIAL })).toBe(
      "With at least 10 comments, r/NBA's most hated player is Tiny (unofficial).",
    )
  })
})

const ranks = (neg: number | null, pos: number | null) => ({ neg, pos, volume: 5, polar: 7 })

describe('playerVerdict', () => {
  const league = { neg: 400, neu: 400, pos: 200, total: 1_000 } // 40% neg, 20% pos
  const base = { official: 100, tracked: 223, league }
  const allRanks = { neg: 31, pos: 40, volume: 50, polar: 60 }

  it('names a hated player defended when his positive share meets the league', () => {
    const v = playerVerdict({ ...base, name: 'A', counts: row('A', 50, 25, 25), ranks: ranks(3, 9), allRanks })
    expect(v).toEqual({ sentence: "r/NBA's 3rd most hated player, and its 9th most loved: hated and defended.", standing: 'hated-defended' })
  })

  it('names a hated player alone when it does not', () => {
    const v = playerVerdict({ ...base, name: 'A', counts: row('A', 50, 40, 10), ranks: ranks(3, 51), allRanks })
    expect(v).toEqual({ sentence: "r/NBA's 3rd most hated player, and only its 51st most loved: hated and alone.", standing: 'hated-alone' })
  })

  it('leads with love when the positive rank is better, argued about when his negative share meets the league', () => {
    const v = playerVerdict({ ...base, name: 'A', counts: row('A', 45, 10, 45), ranks: ranks(12, 2), allRanks })
    expect(v).toEqual({ sentence: "r/NBA's 2nd most loved player, and its 12th most hated: loved and argued about.", standing: 'loved-argued' })
    const w = playerVerdict({ ...base, name: 'A', counts: row('A', 10, 40, 50), ranks: ranks(60, 1), allRanks })
    expect(w).toEqual({ sentence: "r/NBA's 1st most loved player, and only its 60th most hated: loved, no argument.", standing: 'loved-settled' })
  })

  it('treats a tie as hate-led', () => {
    expect(playerVerdict({ ...base, name: 'A', counts: row('A', 50, 25, 25), ranks: ranks(4, 4), allRanks }).standing).toBe('hated-defended')
  })

  it('writes the unofficial note under the minimum, with the shortfall and the all-player rank', () => {
    const v = playerVerdict({ ...base, name: 'A', counts: row('A', 40, 30, 20), ranks: ranks(null, null), allRanks })
    expect(v).toEqual({
      sentence: 'Unofficial: 90 comments, 10 short of the official minimum of 100. Among all 223 tracked players he would rank 31st most hated.',
      standing: 'unofficial',
    })
  })
})

describe('rankChips', () => {
  const league = { neg: 400, neu: 400, pos: 200, total: 1_000 }
  const input = { name: 'A', counts: row('A', 50, 25, 25), official: 100, tracked: 223, league, allRanks: { neg: 31, pos: 40, volume: 50, polar: 60 } }

  it('links each lens to the leaderboard in that lens, the neg lens to the bare board', () => {
    const chips = rankChips({ ...input, ranks: { neg: 3, pos: 9, volume: 5, polar: 7 } })
    expect(chips.map((c) => [c.label, c.href, c.official])).toEqual([
      ['3rd most hated', '/', true],
      ['9th most loved', '/?lens=pos', true],
      ['5th most discussed', '/?lens=volume', true],
      ['7th most argued about', '/?lens=polar', true],
    ])
  })

  it('falls back to the all-player rank, hollow, opening the board with every row, for an unofficial player', () => {
    const chips = rankChips({ ...input, ranks: { neg: null, pos: null, volume: null, polar: null } })
    expect(chips[0]).toEqual({ lens: 'neg', rank: 31, official: false, label: '31st most hated', href: '/?all=1' })
    expect(chips[1]!.href).toBe('/?lens=pos&all=1')
  })
})
