import { describe, expect, it } from 'vitest'

import type { TeamsRow } from '../data/types.gen'
import { deltaLists, fanRosterMatrix, type MatrixRow } from './fanbase'
import { cellSentence, cropGrid, deltaLimit, describePair, gridCells, gridSummary, gridTeams, landingLede, minPresets, moveFocus, pairCells, pairKey, pairSpoken, pickerGroups, rampMix, splitKey, tipSide, windowAround } from './league'
import type { Counts } from './types'

const c = (neg: number, neu: number, pos: number): Counts => ({ neg, neu, pos, total: neg + neu + pos })
const LAL = 'Los Angeles Lakers'
const BOS = 'Boston Celtics'
const MIA = 'Miami Heat'

const team = (name: string, abbreviation: string, conference: string): TeamsRow => ({ team: name, abbreviation, conference, team_id: abbreviation.length, logo_url: `https://m/${abbreviation}.svg` })
const TEAMS = [team(LAL, 'LAL', 'West'), team(BOS, 'BOS', 'East'), team(MIA, 'MIA', 'East')]
const BY_NAME = new Map(TEAMS.map((t) => [t.team, t]))

// Player-grain rows summed to fan × roster cells; the comments state the rates.
const row = (fan: string, roster: string | null, neg: number, neu: number, pos: number): MatrixRow => ({ fan, roster, ...c(neg, neu, pos) })
// Lakers usual 140/300 neg (47%), 70/300 pos (23%); Celtics usual 108/300 neg (36%), 85/300 pos (28%);
// Heat usual 51/210 neg (24%), 85/210 pos (40%). No two Δs tie.
const ROWS: MatrixRow[] = [
  row(LAL, LAL, 30, 50, 20), // own fans
  row(BOS, LAL, 60, 20, 20), // Celtics fans on the Lakers: 60% neg → Δ +13.3, the lead grudge; 20% pos → Δ −3.3
  row(MIA, LAL, 50, 20, 30), // Heat fans on the Lakers: Δneg +3.3, the kindest; 30% pos → Δ +6.7, the lead flowers
  row(LAL, BOS, 40, 40, 20), // Lakers fans on the Celtics: Δneg +4; Δpos −8.3
  row(BOS, BOS, 20, 40, 40),
  row(MIA, BOS, 48, 27, 25), // Heat fans on the Celtics: Δneg +12; Δpos −3.3
  row(LAL, MIA, 1, 4, 5), // n=10: under a floor of 20
  row(BOS, MIA, 30, 40, 30), // Celtics fans on the Heat: Δneg +5.7; Δpos −10.5
  row(MIA, MIA, 20, 30, 50),
  row(LAL, null, 5, 5, 5), // a free agent belongs to no column
]
const FLOOR = 20
const m = fanRosterMatrix(ROWS)

describe('pairKey', () => {
  it('round-trips through splitKey', () => {
    expect(splitKey(pairKey(LAL, BOS))).toEqual({ fan: LAL, roster: BOS })
  })
})

describe('pairCells', () => {
  it('reads every off-diagonal cell, n² − n of them, keyed', () => {
    const cells = pairCells(m)
    expect(cells).toHaveLength(6)
    expect(cells.map((x) => x.key)).not.toContain(pairKey(LAL, LAL))
    expect(cells.find((x) => x.key === pairKey(LAL, BOS))).toEqual({ key: pairKey(LAL, BOS), ...c(40, 40, 20) })
  })
})

describe('describePair', () => {
  it("labels the pair fans → roster and links to the target's page where the cell is a row", () => {
    expect(describePair(BY_NAME)(pairKey(LAL, BOS))).toEqual({ label: 'Lakers fans → Celtics', href: '/fanbases/bos/#league', logo: 'https://m/BOS.svg' })
  })
})

describe('gridTeams', () => {
  it('orders the axes alphabetically by team name', () => {
    expect(gridTeams(TEAMS).map((t) => t.abbr)).toEqual(['BOS', 'LAL', 'MIA'])
    expect(gridTeams(TEAMS)[0]).toEqual({ abbr: 'BOS', team: BOS, href: '/fanbases/bos/' })
  })
})

describe('gridCells', () => {
  const teams = gridTeams(TEAMS)
  const cells = gridCells(m, teams)

  it('reads every cell, the diagonal included, by row then column', () => {
    expect(cells).toHaveLength(9)
    expect(cells.map((x) => `${x.f}${x.r}`)).toEqual(['00', '01', '02', '10', '11', '12', '20', '21', '22'])
  })

  it("takes each Δ from summed counts against the roster's usual", () => {
    // Celtics fans (row 0) on the Lakers (column 1): 60% against 140/300.
    expect(cells.find((x) => x.f === 0 && x.r === 1)).toEqual({ f: 0, r: 1, n: 100, neg: 60, dneg: 0.1333 })
    // Own fans keep their cell; the page draws it as the diagonal.
    expect(cells.find((x) => x.f === 1 && x.r === 1)?.n).toBe(100)
  })
})

describe('deltaLimit', () => {
  it('is the farther end from zero', () => {
    expect(deltaLimit([-0.13, 0.2])).toBe(0.2)
    expect(deltaLimit([-0.25, 0.1])).toBe(0.25)
  })
})

describe('minPresets', () => {
  it('multiplies the published floor', () => {
    expect(minPresets(FLOOR)).toEqual([20, 40, 100, 200])
  })
})

describe('cellSentence', () => {
  const teams = gridTeams(TEAMS)
  const cells = gridCells(m, teams)
  const at = (f: number, r: number) => cells.find((x) => x.f === f && x.r === r)!

  it('reads a cell at the floor: rate, Δ against the usual, n', () => {
    expect(cellSentence(at(0, 1), teams, FLOOR)).toBe("Celtics fans on Lakers players — 60% negative, 13 points above the Lakers' usual 47%, from 100 comments.")
  })

  it('says below when kinder, at when level, and one point in the singular', () => {
    expect(cellSentence({ f: 1, r: 0, n: 100, neg: 30, dneg: -0.0667 }, teams, FLOOR)).toBe("Lakers fans on Celtics players — 30% negative, 7 points below the Celtics' usual 37%, from 100 comments.")
    expect(cellSentence({ f: 1, r: 0, n: 100, neg: 37, dneg: 0.002 }, teams, FLOOR)).toBe("Lakers fans on Celtics players — 37% negative, at the Celtics' usual 37%, from 100 comments.")
    expect(cellSentence({ f: 1, r: 0, n: 100, neg: 37, dneg: 0.012 }, teams, FLOOR)).toBe("Lakers fans on Celtics players — 37% negative, 1 point above the Celtics' usual 36%, from 100 comments.")
  })

  it('names the shortfall under the floor', () => {
    expect(cellSentence(at(1, 2), teams, FLOOR)).toBe('Lakers fans on Heat players — 10 comments, under the minimum of 20.')
  })

  it('sends the diagonal to the team page', () => {
    expect(cellSentence(at(2, 2), teams, FLOOR)).toBe('Heat fans on their own players — read on the team page.')
  })
})

describe('the sentences', () => {
  const lists = deltaLists(pairCells(m), (key) => m.rosterAverage.get(splitKey(key).roster)!, FLOOR, describePair(BY_NAME))

  it('ranks the pairs at the floor, both ways', () => {
    expect(lists.eligible).toBe(5)
    expect(lists.grudges.map((r) => r.label)).toEqual(['Celtics fans → Lakers', 'Heat fans → Celtics', 'Celtics fans → Heat', 'Lakers fans → Celtics', 'Heat fans → Lakers'])
    expect(lists.flowers[0]!.label).toBe('Heat fans → Lakers')
  })

  it('speaks a list row: rate, Δ against the usual, n', () => {
    expect(pairSpoken(lists.grudges[0]!, 'negative')).toBe("Celtics fans on Lakers players: 60% negative, 13 points above the Lakers' usual 47%, from 100 comments.")
    expect(pairSpoken(lists.flowers.at(-1)!, 'positive')).toBe("Celtics fans on Heat players: 30% positive, 10 points below the Heat' usual 40%, from 100 comments.")
  })

  it('lede: the lead grudge and the lead flowers over the eligible pairs', () => {
    expect(landingLede(lists, 6, FLOOR)).toBe(
      "Across the 5 of 6 fan–roster pairs with at least 20 comments, the biggest grudge is Celtics fans on the Lakers, 13 points more negative than the Lakers' usual; the warmest flowers are Heat fans on the Lakers, 7 points more positive than the Lakers' usual.",
    )
  })

  it('grid caption: shape, floor, the two ends by negative Δ, signed', () => {
    expect(gridSummary(lists, 3, 6, FLOOR)).toBe(
      "3 fanbases on 3 rosters, each cell the fanbase's negative rate against the roster's usual: 5 of 6 pairs have at least 20 comments. Harshest: Celtics fans on Lakers players (+13 pts); kindest: Heat fans on Lakers players (+3 pts).",
    )
  })
})

describe('rampMix', () => {
  it('runs bone-text mixes up to the dead band, then ink-text mixes past it', () => {
    expect(rampMix(0, 'heat')).toEqual({ mix: 0, bright: false })
    expect(rampMix(0.3, 'heat')).toEqual({ mix: 37, bright: false })
    expect(rampMix(0.6, 'heat')).toEqual({ mix: 88, bright: true })
    expect(rampMix(1, 'heat')).toEqual({ mix: 100, bright: true })
    expect(rampMix(0.3, 'ice')).toEqual({ mix: 25, bright: false })
    expect(rampMix(0.8, 'ice')).toEqual({ mix: 80, bright: true })
  })

  it('clamps beyond the limit', () => {
    expect(rampMix(1.4, 'ice')).toEqual({ mix: 100, bright: true })
    expect(rampMix(-0.2, 'heat')).toEqual({ mix: 0, bright: false })
  })
})

describe('tipSide', () => {
  it('hangs inward by column third', () => {
    expect([0, 9, 10, 19, 20, 29].map((c) => tipSide(c, 30))).toEqual(['start', 'start', 'centre', 'centre', 'end', 'end'])
  })
})

describe('moveFocus', () => {
  it('steps along a row and column, clamped at the edges', () => {
    expect(moveFocus(0, 1, 'ArrowRight', 3)).toEqual({ r: 0, c: 2 })
    expect(moveFocus(0, 2, 'ArrowRight', 3)).toBeNull()
    expect(moveFocus(2, 0, 'ArrowUp', 3)).toEqual({ r: 1, c: 0 })
    expect(moveFocus(1, 0, 'ArrowLeft', 3)).toBeNull()
  })

  it('skips the diagonal, and stays put when the skip would leave the grid', () => {
    expect(moveFocus(1, 0, 'ArrowRight', 3)).toEqual({ r: 1, c: 2 })
    expect(moveFocus(0, 1, 'ArrowDown', 3)).toEqual({ r: 2, c: 1 })
    expect(moveFocus(1, 2, 'ArrowLeft', 3)).toEqual({ r: 1, c: 0 })
    expect(moveFocus(2, 1, 'ArrowDown', 3)).toBeNull()
    expect(moveFocus(1, 2, 'ArrowDown', 3)).toBeNull()
  })

  it('goes to the row ends, minus the diagonal', () => {
    expect(moveFocus(0, 2, 'Home', 3)).toEqual({ r: 0, c: 1 })
    expect(moveFocus(1, 2, 'Home', 3)).toEqual({ r: 1, c: 0 })
    expect(moveFocus(2, 0, 'End', 3)).toEqual({ r: 2, c: 1 })
    expect(moveFocus(0, 1, 'a', 3)).toBeNull()
  })
})

describe('cropGrid', () => {
  const teams = gridTeams(TEAMS)
  const cells = gridCells(m, teams)

  it('keeps the named teams and re-indexes their cells', () => {
    const crop = cropGrid(teams, cells, [0, 2])
    expect(crop.teams.map((t) => t.abbr)).toEqual(['BOS', 'MIA'])
    expect(crop.cells.map((x) => `${x.f}${x.r}`)).toEqual(['00', '01', '10', '11'])
    expect(crop.cells[1]!.n).toBe(cells.find((x) => x.f === 0 && x.r === 2)!.n)
  })

  it("windows a pair's teams and the run after the first of them", () => {
    expect(windowAround(3, 8, 6, 30)).toEqual([3, 4, 5, 6, 7, 8])
    expect(windowAround(20, 3, 6, 30)).toEqual([3, 4, 5, 6, 7, 20])
    expect(windowAround(28, 29, 6, 30)).toEqual([28, 29])
  })
})

describe('pickerGroups', () => {
  it('groups by conference, West first, alphabetical inside', () => {
    const groups = pickerGroups(TEAMS)
    expect(groups.map((g) => g.conference)).toEqual(['West', 'East'])
    expect(groups[1]!.teams.map((t) => t.abbr)).toEqual(['BOS', 'MIA'])
    expect(groups[0]!.teams[0]).toEqual({ abbr: 'LAL', name: LAL, href: '/fanbases/lal/', logo: 'https://m/LAL.svg' })
  })
})
