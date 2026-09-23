import { describe, expect, it } from 'vitest'

import { deltaLists, fanbaseVerdict, fanRosterMatrix, fewEligibleSentence, type GapRow, gapRows, gapSummary, leagueSummary, type MatrixRow, targetsSummary } from './fanbase'
import { groupBy } from './group'
import type { Counts } from './types'

const c = (neg: number, neu: number, pos: number): Counts => ({ neg, neu, pos, total: neg + neu + pos })
const LAL = 'Los Angeles Lakers'
const BOS = 'Boston Celtics'
const MIA = 'Miami Heat'

// Player-grain rows as the page joins them: fan, the player's roster, counts.
const row = (fan: string, player: string, roster: string | null, neg: number, neu: number, pos: number) => ({ fan, player, roster, ...c(neg, neu, pos) })
const ROWS = [
  row(LAL, 'Austin Reaves', LAL, 30, 50, 20), // own 30% neg
  row(BOS, 'Austin Reaves', LAL, 60, 20, 20),
  row(MIA, 'Austin Reaves', LAL, 50, 30, 20), // rivals 110/200 = 55% → Δ −25
  row(LAL, 'Bronny James', LAL, 2, 2, 1), // own n=5, under a floor of 10
  row(BOS, 'Bronny James', LAL, 10, 5, 5),
  row(LAL, 'Jayson Tatum', BOS, 40, 40, 20), // Lakers fans on the Celtics: 40% neg, 20% pos
  row(BOS, 'Jayson Tatum', BOS, 20, 40, 40),
  row(MIA, 'Jayson Tatum', BOS, 50, 25, 25), // Celtics average 110/300 neg, 85/300 pos
  row(LAL, 'Bam Adebayo', MIA, 10, 40, 50), // Lakers fans on the Heat: 10% neg, 50% pos
  row(BOS, 'Bam Adebayo', MIA, 30, 40, 30),
  row(MIA, 'Bam Adebayo', MIA, 20, 30, 50), // Heat average 60/300 neg, 130/300 pos
  row(LAL, 'Chris Paul', null, 5, 5, 5), // a free agent belongs to no column
]
const MATRIX_ROWS: MatrixRow[] = ROWS.map(({ fan, roster, ...counts }) => ({ fan, roster, ...c(counts.neg, counts.neu, counts.pos) }))
const FLOOR = 10

describe('fanRosterMatrix', () => {
  const m = fanRosterMatrix(MATRIX_ROWS)

  it('sums player rows to fan × roster cells, both ways round', () => {
    expect(m.byFan.get(LAL)!.get(LAL)).toEqual(c(32, 52, 21))
    expect(m.byFan.get(LAL)!.get(BOS)).toEqual(c(40, 40, 20))
    expect(m.byRoster.get(BOS)!.get(LAL)).toEqual(c(40, 40, 20))
  })

  it('reads a roster average over every fanbase from summed counts', () => {
    expect(m.rosterAverage.get(BOS)).toEqual(c(110, 105, 85))
  })

  it('drops free agents: no roster, no column', () => {
    expect([...m.rosterAverage.keys()].toSorted()).toEqual([BOS, LAL, MIA])
    expect(m.byFan.get(LAL)!.size).toBe(3)
  })
})

describe('fanbaseVerdict', () => {
  const counts = c(40, 40, 20)
  it('states the saltiest rank, both rates and n', () => {
    expect(fanbaseVerdict(LAL, counts, { rank: 12, of: 30 })).toBe('The 12th saltiest fanbase of 30: 40% of what Lakers fans say about players is negative, 20% positive, across 100 comments.')
  })
  it('words the two ends without an ordinal', () => {
    expect(fanbaseVerdict(LAL, counts, { rank: 1, of: 30 })).toMatch(/^The saltiest fanbase of 30:/)
    expect(fanbaseVerdict(LAL, counts, { rank: 30, of: 30 })).toMatch(/^The least salty fanbase of 30:/)
  })
})

const ROSTER = [
  { attributed_player: 'Austin Reaves', slug: 'austin-reaves', position: 'G', headshot_url: 'r.png' },
  { attributed_player: 'Bronny James', slug: 'bronny-james', position: 'G', headshot_url: 'b.png' },
]
const BY_PLAYER = groupBy(ROWS, (r) => r.player)

describe('gapRows', () => {
  const rows = gapRows(LAL, ROSTER, BY_PLAYER, FLOOR)

  it('reads own fans against every other fanbase summed, in points as a fraction', () => {
    expect(rows[0]!.name).toBe('Austin Reaves')
    expect(rows[0]!.own).toEqual(c(30, 50, 20))
    expect(rows[0]!.rivals).toEqual(c(110, 50, 40))
    expect(rows[0]!.delta).toBeCloseTo(-0.25)
  })

  it('leaves a row under the floor without a Δ, sorted last', () => {
    expect(rows[1]!.name).toBe('Bronny James')
    expect(rows[1]!.delta).toBeNull()
  })
})

describe('gapSummary', () => {
  const gap = (name: string, delta: number | null, ownN = 100): GapRow => ({ name, slug: name, position: null, headshot: '', own: c(0, ownN, 0), rivals: c(1, 1, 1), delta })

  it('counts the players own fans are kinder to and names both extremes', () => {
    const rows = [gap('A', -0.19), gap('B', -0.12), gap('C', 0.02)]
    expect(gapSummary(LAL, rows, FLOOR)).toBe('Lakers fans are kinder than rival fans to 2 of their 3 players: softest on A (-19 pts), hardest on C (+2 pts).')
  })

  it('says all when every judged player is treated kinder, and counts the thin rows', () => {
    const rows = [gap('A', -0.19), gap('B', -0.12), gap('C', null, 5), gap('D', null, 3)]
    expect(gapSummary(LAL, rows, FLOOR)).toBe('Lakers fans are kinder than rival fans to all 2 players: softest on A (-19 pts), hardest on B (-12 pts). 2 more sit under the floor of 10 of their own comments.')
  })

  it('has a one-player wording', () => {
    expect(gapSummary(LAL, gapRows(LAL, ROSTER, BY_PLAYER, FLOOR), FLOOR)).toBe('Lakers fans are 25 points kinder than rival fans to Austin Reaves, their one tracked player with enough of their own comments. 1 more sits under the floor of 10 of their own comments.')
  })

  it('has wordings for no judged row and no roster', () => {
    expect(gapSummary(LAL, [gap('C', null, 5)], FLOOR)).toBe('Lakers fans have fewer than 10 comments about any of their own 1 tracked players, so no gap is shown.')
    expect(gapSummary(LAL, [], FLOOR)).toBe('Lakers fans have no tracked player on their roster.')
  })
})

const m = fanRosterMatrix(MATRIX_ROWS)
const describeRoster = (team: string) => ({ label: team.split(' ').at(-1)!, href: `/fanbases/${team.slice(0, 3).toLowerCase()}/`, logo: `${team}.svg` })
const targets = () => {
  const cells = [...m.byFan.get(LAL)!].filter(([roster]) => roster !== LAL).map(([key, counts]) => ({ key, ...counts }))
  return deltaLists(cells, (roster) => m.rosterAverage.get(roster)!, FLOOR, describeRoster)
}

describe('deltaLists', () => {
  it('ranks each cell by its Δ against its own key\'s baseline, both sentiments', () => {
    const lists = targets()
    expect(lists.eligible).toBe(2)
    expect(lists.grudges.map((r) => r.label)).toEqual(['Celtics', 'Heat'])
    expect(lists.grudges[0]!.delta).toBeCloseTo(0.4 - 110 / 300)
    expect(lists.grudges[0]!.rate).toBeCloseTo(0.4)
    expect(lists.grudges[0]!.baseline).toBeCloseTo(110 / 300)
    expect(lists.flowers.map((r) => r.label)).toEqual(['Heat', 'Celtics'])
    expect(lists.flowers[0]!.delta).toBeCloseTo(0.5 - 130 / 300)
  })

  it('spans zero and every Δ from both lists in one domain', () => {
    const [lo, hi] = targets().domain
    expect(lo).toBeCloseTo(-0.1)
    expect(hi).toBeCloseTo(0.5 - 130 / 300)
  })

  it('drops cells under the floor and carries the description', () => {
    const lists = deltaLists([{ key: BOS, ...c(1, 1, 1) }, { key: MIA, ...c(10, 40, 50) }], (k) => m.rosterAverage.get(k)!, FLOOR, describeRoster)
    expect(lists.eligible).toBe(1)
    expect(lists.grudges[0]).toMatchObject({ key: MIA, label: 'Heat', href: '/fanbases/mia/', logo: 'Miami Heat.svg', n: 100 })
  })
})

describe('the ledes', () => {
  it('names the hardest and warmest targets in points', () => {
    expect(targetsSummary(LAL, targets(), FLOOR)).toBe("Across the 2 rosters Lakers fans have at least 10 comments about, they are hardest on the Celtics (+3 pts negative against that roster's usual) and warmest to the Heat (+7 pts positive against usual).")
  })

  it('names the hardest and warmest fanbases on this roster', () => {
    const cells = [...m.byRoster.get(BOS)!].filter(([fan]) => fan !== BOS).map(([key, counts]) => ({ key, ...counts }))
    const lists = deltaLists(cells, () => m.rosterAverage.get(BOS)!, FLOOR, (fan) => ({ label: `${fan.split(' ').at(-1)} fans`, href: '/', logo: '' }))
    expect(leagueSummary(BOS, lists, FLOOR)).toBe("Of the 2 fanbases with at least 10 comments about Celtics players, Heat fans are hardest on them (+13 pts negative against the Celtics' usual) and Heat fans warmest (-3 pts positive against usual).")
  })

  it('falls to one sentence under two eligible rows, on either side', () => {
    expect(fewEligibleSentence(LAL, 1, FLOOR, 'targets')).toBe('Only 1 roster has at least 10 comments from Lakers fans, too few to rank.')
    expect(fewEligibleSentence(LAL, 0, FLOOR, 'fans')).toBe('Only 0 fanbases have at least 10 comments about Lakers players, too few to rank.')
    expect(targetsSummary(LAL, { grudges: [], flowers: [], eligible: 1, domain: [0, 0] }, FLOOR)).toMatch(/^Only 1 roster/)
  })
})
