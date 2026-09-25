import { describe, expect, it } from 'vitest'

import type { FanTeamOverallRow, PlayersRow } from '../data/types.gen'
import { heroSentence, playerVerdict, type VerdictInput } from '../lib/annotate'
import { fanbaseVerdict } from '../lib/fanbase'
import { rankBy } from '../lib/metrics'
import type { Standing } from '../lib/standings'
import type { Counts } from '../lib/types'
import { BAR_WIDTH, barSegments, boardCard, cardHref, idLine, playerCard, teamCard } from './model'

const c = (neg: number, neu: number, pos: number): Counts => ({ neg, neu, pos, total: neg + neu + pos })

const PLAYER: PlayersRow = {
  attributed_player: 'Draymond Green',
  slug: 'draymond-green',
  roster_team: 'Golden State Warriors',
  conference: 'West',
  player_id: 203110,
  headshot_url: 'https://example.test/media/headshots/203110.png',
  position: 'F',
  birth_date: null,
  experience: null,
  school: null,
  jersey_number: '23',
  height: null,
  weight: null,
}

const OFFICIAL = 100
const ranks = <T>(v: T) => ({ neg: v, pos: v, volume: v, polar: v })
const input = (counts: Counts, rank: number | null, allRank: number): VerdictInput => ({
  name: PLAYER.attributed_player,
  counts,
  official: OFFICIAL,
  ranks: ranks(rank),
  allRanks: ranks(allRank),
  tracked: 223,
  league: c(400, 400, 200),
})

describe('barSegments', () => {
  it('runs negative → neutral → positive with the page labels', () => {
    const segs = barSegments(c(51, 43, 6))
    expect(segs.map((s) => s.key)).toEqual(['neg', 'neu', 'pos'])
    expect(segs.map((s) => s.label)).toEqual(['51.0%', '43.0%', '6.0%'])
    expect(segs[2]!.under).toBe('6.0% positive')
  })

  it('keeps a label inside only where the hero rule says it fits', () => {
    const segs = barSegments(c(96, 1, 3), BAR_WIDTH)
    expect(segs.map((s) => s.labelFits)).toEqual([true, false, false])
  })
})

describe('idLine', () => {
  it('reads team · position · number, and Free agent without a roster team', () => {
    expect(idLine(PLAYER, 'GSW')).toBe('GSW · F · #23')
    expect(idLine({ ...PLAYER, jersey_number: null }, 'GSW')).toBe('GSW · F')
    expect(idLine({ ...PLAYER, roster_team: null }, null)).toBe('Free agent')
  })
})

describe('playerCard', () => {
  it("carries the page header's verdict sentence, official", () => {
    const i = input(c(51, 43, 6), 1, 1)
    const card = playerCard(i, PLAYER, 'GSW', '2025-26')
    expect(card.sentence).toBe(playerVerdict(i).sentence)
    expect(card).toMatchObject({ kind: 'player', name: 'Draymond Green', eyebrow: 'GSW · F · #23', stamp: null, nLine: 'n=100 comments about Draymond Green', image: PLAYER.headshot_url })
  })

  it('stamps an unofficial player and keeps his unofficial note', () => {
    const i = input(c(9, 1, 0), null, 31)
    const card = playerCard(i, { ...PLAYER, roster_team: null }, null, '2025-26')
    expect(card.sentence).toBe(playerVerdict(i).sentence)
    expect(card.sentence).toMatch(/^Unofficial:/)
    expect(card).toMatchObject({ stamp: 'unofficial', eyebrow: 'Free agent' })
  })
})

describe('teamCard', () => {
  const LAL: FanTeamOverallRow = {
    fan_team: 'Los Angeles Lakers',
    neg_count: 40,
    neu_count: 40,
    pos_count: 20,
    comment_count: 100,
    neg_rate: 0,
    pos_rate: 0,
    net_sentiment: 0,
    polarization: 0,
    abbreviation: 'LAL',
    conference: 'West',
    logo_url: 'https://example.test/media/logos/1610612747.svg',
  }

  it("carries the team header's sentence and title", () => {
    const counts = c(40, 40, 20)
    const card = teamCard(LAL, counts, 12, 30, '2025-26')
    expect(card.sentence).toBe(fanbaseVerdict('Los Angeles Lakers', counts, { rank: 12, of: 30 }))
    expect(card).toMatchObject({
      kind: 'team',
      title: 'Lakers fans',
      eyebrow: 'LAL · West',
      nLine: 'n=100 comments by Lakers fans about tracked players',
      stamp: null,
      image: LAL.logo_url,
    })
  })
})

const row = (name: string, counts: Counts): Standing => ({ ...counts, name, slug: name.toLowerCase() })

describe('boardCard', () => {
  const ROWS = [row('Leader', c(55, 30, 15)), row('Second', c(30, 50, 20)), row('Tiny', c(9, 1, 0))]
  const headline = { count: 1_234_567, players: 223 }

  it('names the official #1 with the hero sentence', () => {
    const ranked = rankBy(ROWS, 'neg', OFFICIAL)
    const card = boardCard(ranked, OFFICIAL, headline, (n) => `https://example.test/${n}.png`, '2025-26')
    expect(card.sentence).toBe(heroSentence({ ranked, lens: 'neg', threshold: OFFICIAL, official: OFFICIAL }))
    expect(card.sentence).toBe("r/NBA's most hated player is Leader.")
    expect(card).toMatchObject({ kind: 'board', name: 'Leader', kicker: '1,234,567 comments about 223 players', nLine: 'n=100 comments about Leader', image: 'https://example.test/Leader.png' })
  })

  it('refuses a board nobody qualifies for', () => {
    expect(() => boardCard(rankBy(ROWS, 'neg', 99_999), 99_999, headline, () => '', '2025-26')).toThrow(/no player reaches/)
  })
})

describe('cardHref', () => {
  it('addresses the three kinds', () => {
    expect(cardHref.player('draymond-green')).toBe('/player/draymond-green/card.png')
    expect(cardHref.team('LAL')).toBe('/fanbases/lal/card.png')
    expect(cardHref.board).toBe('/card.png')
  })
})
