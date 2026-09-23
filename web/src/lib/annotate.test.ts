import { describe, expect, it } from 'vitest'

import { annotate, heroSentence, type Named } from './annotate'
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
