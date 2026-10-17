import { describe, expect, it } from 'vitest'

import { CONFERENCES, headerLabel, headerText, layoutMap, NO_ROSTER_KEY, NO_ROSTER_NAME, officialCount, type PopulationRow, populationRows, populationView, showNet, teamNet, tileBase, tileLabel, tileText } from './population'
import { player as dimPlayer, TEAMS } from './season.fixture'

const OFFICIAL = 100

const player = (name: string, team: string | null, conference: string | null, neg: number, neu: number, pos: number, status: string | null = null): PopulationRow => ({
  name,
  slug: name.toLowerCase().replace(/ /g, '-'),
  team: team && `${team} Full`,
  abbr: team,
  logo: team && `https://x/${team}.svg`,
  conference,
  status,
  neg,
  neu,
  pos,
  total: neg + neu + pos,
})

// Two West rosters, one East, and two players with no team; LAL the largest.
const rows = [
  player('Luka Doncic', 'LAL', 'West', 60, 30, 10),
  player('LeBron James', 'LAL', 'West', 100, 100, 100),
  player('Victor Wembanyama', 'SAS', 'West', 50, 100, 100),
  player('Jalen Brunson', 'NYK', 'East', 40, 40, 40),
  player('Chris Paul', null, null, 30, 20, 10, 'Retired'),
  player('Ben Simmons', null, null, 20, 20, 20, 'Free agent'),
  player('Stephon Castle', 'SAS', 'West', 10, 10, 10),
]

describe('populationView', () => {
  it('groups by roster, the largest group and the largest player first, the seven as one group', () => {
    const v = populationView(rows, { scope: 'all', conf: 'all', zoom: null, official: OFFICIAL })
    expect(v.groups.map((g) => g.key)).toEqual(['LAL', 'SAS', 'NYK', NO_ROSTER_KEY])
    expect(v.groups[0]!.players.map((p) => p.name)).toEqual(['LeBron James', 'Luka Doncic'])
    const none = v.groups.at(-1)!
    expect(none.name).toBe(NO_ROSTER_NAME)
    expect(none.abbr).toBeNull()
    expect(none.logo).toBeNull()
    expect(none.net).toBeNull()
  })

  it('carries each group as the name, logo and counts of its roster, net summed from counts', () => {
    const v = populationView(rows, { scope: 'all', conf: 'all', zoom: null, official: OFFICIAL })
    const lal = v.groups[0]!
    expect(lal).toMatchObject({ abbr: 'LAL', name: 'LAL Full', logo: 'https://x/LAL.svg' })
    expect(lal.counts).toEqual({ neg: 160, neu: 130, pos: 110, total: 400 })
    expect(lal.net).toBeCloseTo((110 - 160) / 400, 12)
  })

  it('writes the eyebrow from the rows, teams counted without the no-roster group', () => {
    const v = populationView(rows, { scope: 'all', conf: 'all', zoom: null, official: OFFICIAL })
    expect(v.eyebrow).toBe('Population · 920 comments about 7 players on 3 teams')
    expect(v.crumb).toBe('Click a team to zoom')
    expect(v.zoomed).toBeNull()
  })

  it('under Official keeps the players at the minimum, and the header net follows the boxes shown', () => {
    const v = populationView(rows, { scope: 'official', conf: 'all', zoom: null, official: OFFICIAL })
    expect(v.groups.map((g) => g.key)).toEqual(['LAL', 'SAS', 'NYK'])
    expect(v.groups[1]!.players.map((p) => p.name)).toEqual(['Victor Wembanyama'])
    expect(v.groups[1]!.net).toBeCloseTo((100 - 50) / 250, 12)
    expect(v.eyebrow).toBe('Population · 770 comments about 4 players on 3 teams')
  })

  it('a conference keeps its rosters and hides the no-roster group', () => {
    const v = populationView(rows, { scope: 'all', conf: 'West', zoom: null, official: OFFICIAL })
    expect(v.groups.map((g) => g.key)).toEqual(['LAL', 'SAS'])
    expect(v.eyebrow).toBe('Western Conference · 680 comments about 4 players on 2 teams')
    expect(populationView(rows, { scope: 'all', conf: 'East', zoom: null, official: OFFICIAL }).eyebrow).toBe('Eastern Conference · 120 comments about 1 players on 1 teams')
  })

  it('zoomed shows the one group, its eyebrow without teams, and the crumb names it', () => {
    const v = populationView(rows, { scope: 'all', conf: 'all', zoom: 'SAS', official: OFFICIAL })
    expect(v.groups.map((g) => g.key)).toEqual(['SAS'])
    expect(v.zoomed?.key).toBe('SAS')
    expect(v.eyebrow).toBe('280 comments about 2 players')
    expect(v.crumb).toBe('SAS Full · 2 players')
  })

  it('zooms the no-roster group by its key', () => {
    const v = populationView(rows, { scope: 'all', conf: 'all', zoom: NO_ROSTER_KEY, official: OFFICIAL })
    expect(v.groups.map((g) => g.name)).toEqual([NO_ROSTER_NAME])
    expect(v.crumb).toBe('No roster team · 2 players')
  })

  it('a zoom on a group the view no longer holds falls back to the whole map', () => {
    const v = populationView(rows, { scope: 'all', conf: 'West', zoom: NO_ROSTER_KEY, official: OFFICIAL })
    expect(v.zoomed).toBeNull()
    expect(v.groups).toHaveLength(2)
  })

  it('counts the official players and sums a team net from counts', () => {
    expect(officialCount(rows, OFFICIAL)).toBe(4)
    expect(teamNet([player('a', 'X', 'East', 10, 0, 30), player('b', 'X', 'East', 30, 0, 10)])).toBe(0)
  })

  it('lists the three conference choices in order', () => {
    expect(CONFERENCES.map((c) => c.key)).toEqual(['all', 'East', 'West'])
  })
})

const overall = (name: string, neg: number, neu: number, pos: number) => ({ attributed_player: name, neg_count: neg, neu_count: neu, pos_count: pos, comment_count: neg + neu + pos })
type Pixels = { x: number; y: number; w: number; h: number }
const inside = (b: Pixels, box: Pixels) => b.x >= box.x && b.y >= box.y && b.x + b.w <= box.x + box.w && b.y + b.h <= box.y + box.h

describe('populationRows', () => {
  const copy = { 'chris-paul': { status: 'Retired' as const, text: 'He retired.' } }
  const tables = {
    players: [dimPlayer('Victor Wembanyama'), dimPlayer('Jalen Brunson', { roster_team: 'New York Knicks', conference: 'East' }), dimPlayer('Chris Paul', { roster_team: null, conference: null })],
    player_overall: [overall('Victor Wembanyama', 50, 100, 100), overall('Chris Paul', 30, 20, 10), overall('Jalen Brunson', 40, 40, 40)],
    teams: TEAMS,
  }

  it('joins each player with comments to his roster, logo and conference, and his status without one', () => {
    const rs = populationRows(tables, copy)
    expect(rs.map((r) => r.name)).toEqual(['Victor Wembanyama', 'Chris Paul', 'Jalen Brunson'])
    expect(rs[0]).toMatchObject({ slug: 'victor-wembanyama', team: 'San Antonio Spurs', abbr: 'SAS', logo: '', conference: 'West', status: null, total: 250 })
    expect(rs[1]).toMatchObject({ team: null, abbr: null, logo: null, conference: null, status: 'Retired' })
    expect(rs[2]).toMatchObject({ abbr: 'NYK', conference: 'East' })
  })

  it('fails the build on a player without a dimension row or on a roster the teams table lacks', () => {
    expect(() => populationRows({ ...tables, player_overall: [overall('Nobody', 1, 1, 1)] }, copy)).toThrow(/no players row/)
    expect(() => populationRows({ ...tables, players: [dimPlayer('Victor Wembanyama', { roster_team: 'Seattle' })] }, copy)).toThrow(/teams does not list/)
  })
})

describe('layoutMap', () => {
  const W = 1000
  const H = 600
  const whole = populationView(rows, { scope: 'all', conf: 'all', zoom: null, official: OFFICIAL })

  it('gives every group a header and lays its players under it, inside the box', () => {
    const { headers, tiles } = layoutMap(whole, W, H)
    expect(headers.map((h) => h.group.key)).toEqual(['LAL', 'SAS', 'NYK', NO_ROSTER_KEY])
    expect(tiles).toHaveLength(rows.length)
    for (const h of headers) {
      expect(inside(h, { x: 0, y: 0, w: W, h: H })).toBe(true)
      for (const t of tiles.filter((tile) => tile.group === h.group)) {
        expect(t.y).toBeGreaterThanOrEqual(h.y + h.h)
        expect(t.x).toBeGreaterThanOrEqual(h.x)
        expect(t.x + t.w).toBeLessThanOrEqual(h.x + h.w)
      }
    }
  })

  it('lays tiles on whole pixels, the largest player first in each group', () => {
    const { tiles } = layoutMap(whole, W, H)
    for (const t of tiles) for (const k of ['x', 'y', 'w', 'h'] as const) expect(Number.isInteger(t[k]), k).toBe(true)
    const lal = tiles.filter((t) => t.group.key === 'LAL')
    expect(lal.map((t) => t.row.name)).toEqual(['LeBron James', 'Luka Doncic'])
  })

  it('zoomed, has no headers and the players fill the box', () => {
    const zoomed = populationView(rows, { scope: 'all', conf: 'all', zoom: 'SAS', official: OFFICIAL })
    const { headers, tiles } = layoutMap(zoomed, W, H)
    expect(headers).toEqual([])
    expect(tiles.map((t) => t.row.name)).toEqual(['Victor Wembanyama', 'Stephon Castle'])
    expect(Math.max(...tiles.map((t) => t.x + t.w))).toBe(W - 1)
    expect(Math.max(...tiles.map((t) => t.y + t.h))).toBe(H - 1)
  })

  it('drops the header strip from a group too small to hold one', () => {
    const { headers, tiles } = layoutMap(whole, 120, 60)
    expect(headers.length).toBeLessThan(whole.groups.length)
    expect(tiles.length).toBeGreaterThan(0)
  })

  it('is empty for an empty box', () => {
    expect(layoutMap(whole, 0, 0)).toEqual({ headers: [], tiles: [] })
  })
})

describe('headerLabel', () => {
  const v = populationView(rows, { scope: 'all', conf: 'all', zoom: null, official: OFFICIAL })
  const lal = v.groups[0]!
  const none = v.groups.at(-1)!

  it('sheds the count, then the net, as a team header narrows', () => {
    expect(headerLabel(lal, 300)).toEqual({ title: 'LAL', detail: '400 · −13 net' })
    expect(headerLabel(lal, 150)).toEqual({ title: 'LAL', detail: '−13 net' })
    expect(headerLabel(lal, 60)).toEqual({ title: 'LAL', detail: '' })
  })

  it('shortens the no-roster name and shows its count only when wide, never a net', () => {
    expect(headerLabel(none, 300)).toEqual({ title: NO_ROSTER_NAME, detail: '120' })
    expect(headerLabel(none, 120)).toEqual({ title: 'No roster', detail: '120' })
    expect(headerLabel(none, 90)).toEqual({ title: 'No roster', detail: '' })
    expect(headerLabel(none, 50)).toEqual({ title: NO_ROSTER_KEY, detail: '' })
  })

  it('speaks the team, its comments, its players and its net; the no-roster group without a net', () => {
    expect(headerText(lal)).toBe('LAL Full · 400 comments · 2 players · team net −13')
    expect(headerText(none)).toBe('No roster team · 120 comments · 2 players')
  })
})

describe('tileLabel', () => {
  it('puts the first name over the surname on a wide tile, at the base size', () => {
    expect(tileLabel('LeBron James', 200, 120, 30)).toEqual({ fontSize: 30, line1: 'LeBron', line2: 'James' })
  })

  it('steps the size down to fit two lines, then falls back to the surname alone', () => {
    const two = tileLabel('Victor Wembanyama', 90, 60, 30)!
    expect(two.line2).toBe('Wembanyama')
    expect(two.fontSize).toBeLessThan(30)
    const one = tileLabel('Victor Wembanyama', 90, 24, 30)!
    expect(one).toMatchObject({ line1: 'Wembanyama', line2: '' })
  })

  it('is null on a sliver, and one line for a one-word name', () => {
    expect(tileLabel('LeBron James', 20, 12, 30)).toBeNull()
    expect(tileLabel('Nene', 100, 40, 20)).toEqual({ fontSize: 20, line1: 'Nene', line2: '' })
  })

  it('scales the base size by the tile area within bounds', () => {
    expect(tileBase(10, 10)).toBe(10)
    expect(tileBase(1000, 1000)).toBe(40)
    expect(tileBase(130, 130)).toBeCloseTo(20, 9)
  })

  it('shows the net line only under a name with room below it', () => {
    const label = tileLabel('LeBron James', 200, 120, 30)
    expect(showNet(label, 200, 120)).toBe(true)
    expect(showNet(label, 200, 70)).toBe(false)
    expect(showNet(label, 50, 120)).toBe(false)
    expect(showNet(null, 200, 120)).toBe(false)
  })
})

describe('tileText', () => {
  it('speaks name, team, comments, the split and the net; status in place of a team', () => {
    expect(tileText(rows[1]!)).toBe('LeBron James · LAL · 300 comments · 33.3% negative, 33.3% positive, net 0')
    expect(tileText(rows[4]!)).toBe('Chris Paul · Retired · no roster team · 60 comments · 50.0% negative, 16.7% positive, net −33')
  })
})
