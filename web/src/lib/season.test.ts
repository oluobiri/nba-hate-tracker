import { describe, expect, it } from 'vitest'

import { negRate } from './metrics'
import type { RecapEntry } from '../data/types.gen'
import {
  type ArcInputs,
  type ArcPoint,
  type ThreadInputs,
  aboveStretch,
  addDays,
  againstLevel,
  arcDomain,
  arcField,
  arcLists,
  arcText,
  arcsLede,
  dayLabel,
  endedAs,
  extremeNights,
  gameComments,
  gameNightSplit,
  harshestNote,
  loudestThreads,
  ledeText,
  nightGameTitle,
  nightPhase,
  nightRows,
  nightText,
  nightWhat,
  nightsLede,
  phaseCounts,
  pooledLine,
  seasonCalendar,
  BANDS,
  bandWeekly,
  bigRoomsMoved,
  fmtPoints,
  fmtPts,
  fmtShare,
  fraction,
  playerAngle,
  playerAngleText,
  recapsByGame,
  roomRows,
  roomSplit,
  roomTable,
  roomTiles,
  roomsLede,
  threadFigure,
  threadText,
  timing,
  warmestNote,
  weekPhase,
} from './season'
import { CAL, TEAMS, daily, game, nightsFrom, player, playerGame, playerRoom, plusDays, post, roomWeek, sentiment, temporal } from './season.fixture'

const cal = seasonCalendar(CAL)
const ABBR = new Map(TEAMS.map((t) => [t.team, t.abbreviation]))

describe('seasonCalendar', () => {
  it('fails naming the date that is missing', () => {
    expect(() => seasonCalendar({ ...CAL, finals_end: null })).toThrow('calendar: finals_end is missing')
  })

  it('names every dated event by its day', () => {
    expect(cal.events.get('2026-02-15')).toBe('All-Star Game')
    expect(cal.events.get('2025-12-16')).toBe('NBA Cup final')
    expect(cal.events.has('2026-02-13')).toBe(false)
  })
})

describe('nightPhase', () => {
  it('folds the play-in and the Finals into the playoffs', () => {
    expect(nightPhase('2025-10-01', cal)).toBe('pre')
    expect(nightPhase('2025-10-21', cal)).toBe('regular')
    expect(nightPhase('2026-04-13', cal)).toBe('regular')
    expect(nightPhase('2026-04-14', cal)).toBe('playoffs')
    expect(nightPhase('2026-06-13', cal)).toBe('playoffs')
    expect(nightPhase('2026-06-14', cal)).toBe('off')
  })
})

describe('nightRows', () => {
  it('sorts the nights, counts the games on each and sets the phase', () => {
    const rows = nightRows([daily('2026-04-14', 1, 1, 1), daily('2026-04-13', 2, 0, 0)], [game('a', '2026-04-14'), game('b', '2026-04-14'), game('c', '2026-04-15')], cal)
    expect(rows.map((n) => n.day)).toEqual(['2026-04-13', '2026-04-14'])
    expect(rows[0]).toMatchObject({ games: 0, phase: 'regular', counts: { neg: 2, neu: 0, pos: 0, total: 2 } })
    expect(rows[1]).toMatchObject({ games: 2, phase: 'playoffs' })
  })
})

describe('pooledLine', () => {
  const nights = nightRows(
    nightsFrom('2025-11-01', [
      [1, 0, 1],
      [3, 0, 1],
      [0, 0, 4],
      [2, 2, 0],
    ]),
    [],
    cal,
  )

  it('sums the window then takes the rate, never the mean of nightly rates', () => {
    const line = pooledLine(nights, 3, 'neg')
    // Nights 1–3: 4 negative of 10; the mean of their rates would be 0.42.
    expect(line[1]).toBeCloseTo(0.4, 10)
    expect(line[2]).toBeCloseTo(5 / 12, 10)
  })

  it('is null where the window would run off the season', () => {
    const line = pooledLine(nights, 3, 'pos')
    expect(line[0]).toBeNull()
    expect(line[3]).toBeNull()
    expect(line[1]).toBeCloseTo(0.6, 10)
  })

  it('is null across an empty window', () => {
    const empty = nightRows(nightsFrom('2025-11-01', [[0, 0, 0], [0, 0, 0], [0, 0, 0]]), [], cal)
    expect(pooledLine(empty, 3, 'neg')).toEqual([null, null, null])
  })
})

describe('phaseCounts and extremeNights', () => {
  const nights = nightRows([daily('2025-10-20', 9, 0, 1), daily('2025-10-21', 300, 500, 200), daily('2025-10-22', 100, 100, 800), daily('2026-06-14', 50, 0, 0)], [], cal)

  it('sums one phase', () => {
    expect(phaseCounts(nights, 'regular')).toEqual({ neg: 400, neu: 600, pos: 1000, total: 2000 })
    expect(phaseCounts(nights, 'pre').total).toBe(10)
  })

  it('names the harshest and the warmest at the floor and the loudest regardless', () => {
    const { harshest, warmest, loudest } = extremeNights(nights, 1000)
    // The 90% night is under the floor; the 100% offseason night too.
    expect(harshest?.day).toBe('2025-10-21')
    expect(warmest?.day).toBe('2025-10-22')
    expect(loudest?.day).toBe('2025-10-21')
  })

  it('has no extremes at the floor when nothing reaches it', () => {
    expect(extremeNights(nights, 5000)).toMatchObject({ harshest: null, warmest: null })
    expect(extremeNights([], 1)).toEqual({ harshest: null, warmest: null, loudest: null })
  })
})

describe('aboveStretch', () => {
  const nights = nightRows(nightsFrom('2026-04-10', Array.from({ length: 10 }, () => [1, 1, 1] as [number, number, number])), [], cal)

  it('runs from the first night above the level, from a day on, to the night the line is back', () => {
    const line = [null, 0.5, 0.5, 0.3, 0.5, 0.5, 0.5, 0.2, 0.5, null]
    // From the play-in start (Apr 14, index 4): Apr 14, 15, 16 above; Apr 17 back.
    expect(aboveStretch(nights, line, 0.4, cal.play_in_start)).toEqual({ from: '2026-04-14', to: '2026-04-17', nights: 3 })
  })

  it('counts to the last drawn night when the line never came back', () => {
    const line = [null, 0.3, 0.3, 0.3, 0.5, 0.5, 0.5, 0.5, 0.5, null]
    expect(aboveStretch(nights, line, 0.4, cal.play_in_start)).toEqual({ from: '2026-04-14', to: null, nights: 5 })
  })

  it('is null when the line never rises above the level', () => {
    expect(aboveStretch(nights, Array(10).fill(0.3), 0.4, cal.play_in_start)).toBeNull()
  })
})

describe('gameNightSplit', () => {
  it('cuts the three phases disjoint and calls a night without a games row no game', () => {
    const nights = nightRows(
      [
        daily('2026-04-13', 10, 0, 0),
        daily('2026-04-14', 20, 0, 0),
        daily('2026-06-02', 30, 0, 0),
        daily('2026-06-03', 40, 0, 0),
        daily('2026-06-13', 50, 0, 0),
        daily('2026-06-14', 60, 0, 0),
        daily('2026-02-15', 7, 0, 0),
      ],
      [game('a', '2026-04-13'), game('b', '2026-06-03'), game('c', '2026-06-13')],
      cal,
    )
    const rows = gameNightSplit(nights, cal)
    expect(rows.map((r) => r.key)).toEqual(['regular', 'playoffs', 'finals'])
    // The All-Star night has no row in games, so it is a regular-season night with no game.
    expect(rows[0]).toMatchObject({ on: { total: 10 }, onNights: 1, off: { total: 7 }, offNights: 1 })
    expect(rows[1]).toMatchObject({ on: { total: 0 }, onNights: 0, off: { total: 50 }, offNights: 2 })
    expect(rows[2]).toMatchObject({ on: { total: 90 }, onNights: 2, off: { total: 0 }, offNights: 0 })
    expect(rows.reduce((n, r) => n + r.onNights + r.offNights, 0)).toBe(6)
  })
})

describe('nightsLede', () => {
  const harsh = nightRows([daily('2026-02-28', 6, 3, 1)], [], cal)[0]!

  it('runs to the last night of the Finals when the stretch outlives them, and says February', () => {
    const lede = nightsLede({ from: '2026-04-14', to: '2026-06-17', nights: 64 }, 0.352, harsh, cal)
    expect(ledeText(lede)).toBe(
      'From the first play-in night on Apr 14 to the last night of the Finals, comments about players never cooled to their regular-season level of 35.2% negative. The single most negative night of the season still came in February.',
    )
    expect(lede.level).toBe('35.2% negative')
  })

  it('names the night the line came back, and the harshest night outside February', () => {
    const may = nightRows([daily('2026-05-02', 6, 3, 1)], [], cal)[0]!
    const lede = nightsLede({ from: '2026-04-14', to: '2026-05-20', nights: 36 }, 0.352, may, cal)
    expect(ledeText(lede)).toContain('until May 20, comments about players')
    expect(ledeText(lede)).toContain('The single most negative night of the season was May 2.')
  })

  it('falls back when the line never rose above the level', () => {
    expect(ledeText(nightsLede(null, 0.352, null, cal))).toBe('Through the playoffs, comments about players held near their regular-season level of 35.2% negative.')
  })
})

describe('harshestNote', () => {
  const nights = nightRows([daily('2026-02-26', 1, 1, 1), daily('2026-02-27', 493, 307, 200), daily('2026-02-28', 502, 298, 200)], [], cal)
  const copy = { day: '2026-02-27', title: 'Dort ejected', text: "Dort's Flagrant 2 on Jokić." }

  it('reads both nights into the words and rings the day after', () => {
    const note = harshestNote(nights, copy, nights[2]!)
    expect(note.head).toBe('Feb 27 · Dort ejected')
    expect(note.text).toBe("Dort's Flagrant 2 on Jokić. 49.3% negative that night, 50.2% the day after.")
    expect(note.shortText).toBe("Dort's Flagrant 2 on Jokić. 49.3%, then 50.2% the day after.")
    expect(note.rate).toBeCloseTo(0.493, 10)
    expect(note.also).toEqual({ day: '2026-02-28', rate: negRate(nights[2]!.counts) })
  })

  it('accepts the harshest night on the day itself', () => {
    expect(() => harshestNote(nights, copy, nights[1]!)).not.toThrow()
  })

  it('fails the build when the night is absent or the harshest night moved', () => {
    expect(() => harshestNote(nights, { ...copy, day: '2026-03-01' }, nights[2]!)).toThrow('season copy: no night on 2026-03-01')
    expect(() => harshestNote(nights, copy, nights[0]!)).toThrow('the harshest night at the floor is 2026-02-26')
    expect(() => harshestNote(nights, copy, null)).toThrow('is none')
  })
})

describe('the warmest night', () => {
  const games = [game('g1', '2026-05-18'), game('g2', '2026-05-18', { home_team: 'New York Knicks', away_team: 'Dallas Mavericks', winner: 'New York Knicks', home_score: 99, away_score: 90 })]

  it('sums each game’s comments about players', () => {
    const byGame = gameComments([sentiment('A', 'g1', 1, 2, 3), sentiment('B', 'g1', 1, 0, 0), sentiment('C', 'g2', 0, 0, 1)])
    expect(byGame.get('g1')).toEqual({ neg: 2, neu: 2, pos: 3, total: 7 })
    expect(byGame.get('g2')?.total).toBe(1)
  })

  it('titles the night by its loudest game, the winner first', () => {
    const loud = new Map([['g2', { neg: 0, neu: 0, pos: 9, total: 9 }]])
    expect(nightGameTitle('2026-05-18', games, loud, ABBR)).toBe('Knicks win over DAL')
    expect(nightGameTitle('2026-05-18', games, new Map([['g1', { neg: 0, neu: 0, pos: 9, total: 9 }]]), ABBR)).toBe('Spurs win at OKC')
    expect(nightGameTitle('2026-05-19', games, loud, ABBR)).toBeNull()
  })

  it('writes the note from the night alone', () => {
    const night = nightRows([daily('2026-05-18', 330, 286, 384)], [], cal)[0]!
    const note = warmestNote(night, 'Spurs win at OKC')
    expect(note).toMatchObject({ pole: 'pos', head: 'May 18 · Spurs win at OKC', shortHead: 'May 18', text: 'The warmest night: 38.4% positive, 33.0% negative.', shortText: 'Warmest: 38.4% positive.', also: null })
    expect(warmestNote(night, null).head).toBe('May 18')
  })
})

describe('the readout words', () => {
  const nights = nightRows([daily('2026-02-15', 1, 1, 2), daily('2026-02-16', 0, 0, 0), daily('2026-02-17', 2, 1, 1)], [game('a', '2026-02-17')], cal)

  it('names the calendar event, else the games, else the phase', () => {
    expect(nightWhat(nights[0]!, cal)).toBe('All-Star Game')
    expect(nightWhat(nights[1]!, cal)).toBe('No games')
    expect(nightWhat(nights[2]!, cal)).toBe('1 game')
    expect(nightWhat({ ...nights[1]!, games: 3 }, cal)).toBe('3 games')
    expect(nightWhat({ ...nights[1]!, phase: 'off' }, cal)).toBe('Offseason')
  })

  it('speaks the night against the regular season', () => {
    expect(againstLevel(0.372, 0.352)).toBe('2.0 points above the regular season.')
    expect(againstLevel(0.3522, 0.352)).toBe('Level with the regular season.')
    expect(againstLevel(null, 0.352)).toBe('')
    expect(nightText(nights[1]!, cal, null, null, 0.352, 7)).toBe('Mon, Feb 16, No games: no comments.')
    expect(nightText(nights[0]!, cal, null, null, 0.352, 7)).toBe('Sun, Feb 15, All-Star Game: 25.0% negative and 50.0% positive of 4 comments; too close to the edge of the season for the 7-night line.')
    expect(nightText(nights[2]!, cal, 0.4, 0.3, 0.352, 7)).toBe('Tue, Feb 17, 1 game: 50.0% negative and 25.0% positive of 4 comments; the 7 nights around it 40.0% negative and 30.0% positive. 4.8 points above the regular season.')
  })

  it('moves and labels days in UTC', () => {
    expect(addDays('2026-02-28', 1)).toBe('2026-03-01')
    expect(addDays('2026-04-14', -1)).toBe('2026-04-13')
    expect(dayLabel('2026-02-27')).toBe('Fri, Feb 27')
  })
})

// --- The rooms ------------------------------------------------------------------

describe('weekPhase', () => {
  it('gives a week the phase most of its nights fall in, so the play-in week is a playoff week', () => {
    // Mon Apr 13 is the last regular-season night; the six after it are play-in and playoffs.
    expect(weekPhase('2026-04-13T00:00:00', cal)).toBe('playoffs')
    expect(weekPhase('2026-04-06T00:00:00', cal)).toBe('regular')
    // Mon Jun 8: Jun 8–13 are Finals nights, Jun 14 is offseason.
    expect(weekPhase('2026-06-08T00:00:00', cal)).toBe('playoffs')
    expect(weekPhase('2026-06-15T00:00:00', cal)).toBe('off')
    expect(weekPhase('2025-10-13T00:00:00', cal)).toBe('pre')
  })

  it('breaks a tie toward the earlier phase', () => {
    // Opening night Tue Oct 21 (toy): Mon Oct 20 is preseason, the other six regular. No tie; shift to make one:
    const tie = seasonCalendar({ ...CAL, opening_night: '2025-10-24' })
    // Mon Oct 20–Thu Oct 23 pre (4), Fri–Sun regular (3).
    expect(weekPhase('2025-10-20T00:00:00', tie)).toBe('pre')
  })
})

describe('roomSplit', () => {
  // One regular-season week and one playoff week; the daily room exists only in the playoffs.
  const RS = '2026-03-02'
  const PO = '2026-04-20'
  const rows = [
    roomWeek('general', RS, 30, 50, 20),
    roomWeek('game_thread', RS, 40, 40, 20),
    roomWeek('general', PO, 20, 20, 10),
    roomWeek('game_thread', PO, 60, 20, 20),
    roomWeek('daily', PO, 5, 5, 0),
    roomWeek('news', '2025-10-06', 1, 1, 1),
  ]
  const split = roomSplit(rows, cal)

  it('pools each phase and adds the two parts of the split up to the rise', () => {
    expect(split.reg).toEqual({ neg: 70, neu: 90, pos: 40, total: 200 })
    expect(split.po).toEqual({ neg: 85, neu: 45, pos: 30, total: 160 })
    expect(split.lift).toBeCloseTo(85 / 160 - 70 / 200, 12)
    expect(split.mix + split.harsh).toBeCloseTo(split.lift, 12)
  })

  it('gives a room missing from one phase the other phase’s rate, so it adds nothing to the tone', () => {
    const chat = split.rooms.find((r) => r.key === 'daily')!
    expect(chat.rateReg).toBeCloseTo(0.5, 12)
    expect(chat.ratePo).toBeCloseTo(0.5, 12)
    expect(chat.harsh).toBe(0)
    expect(chat.mix).toBeGreaterThan(0)
    const news = split.rooms.find((r) => r.key === 'news')!
    expect(news.ratePo).toBe(news.rateReg)
    expect(news.whole.total).toBe(3)
  })

  it('reads the shares and names the rooms', () => {
    const gt = split.rooms.find((r) => r.key === 'game_thread')!
    expect(gt).toMatchObject({ label: 'Game threads', big: true, shareReg: 0.5, sharePo: 100 / 160 })
    expect(gt.shareWhole).toBeCloseTo(200 / 363, 12)
    expect(split.rooms.map((r) => r.key)).toEqual(['daily', 'game_thread', 'general', 'news'])
  })

  it('folds the bands into rows and keeps the largest share for the scale', () => {
    const { rows: bandRows, maxShare } = roomRows(split)
    expect(bandRows.map((r) => r.key)).toEqual(BANDS.map((b) => b.key))
    expect(bandRows[0]).toMatchObject({ key: 'game_thread', reg: { total: 100 }, po: { total: 100 }, shareReg: 0.5 })
    expect(bandRows.at(-1)).toMatchObject({ key: 'rest', reg: { total: 0 }, po: { total: 0 }, shareReg: 0, sharePo: 0 })
    expect(maxShare).toBeCloseTo(100 / 160, 12)
    expect(roomTable(split).map((r) => r.key)).toEqual(['game_thread', 'general', 'daily', 'news'])
  })

  it('lays the bands on the week spine with each week’s phase and total', () => {
    // A consecutive spine: a front-page row every Monday from Oct 6 to Apr 27, the phase rows on top.
    const mondays = Array.from({ length: 30 }, (_, i) => plusDays('2025-10-06', 7 * i))
    const spine = mondays.filter((m) => m !== RS && m !== PO).map((m) => roomWeek('general', m, 1, 1, 1))
    const weekly = bandWeekly([...rows.filter((r) => !r.week.startsWith('2025-10-06')), ...spine, roomWeek('lowlight', PO, 1, 0, 0)], seasonCalendar({ ...CAL, opening_night: '2025-10-06' }))
    expect(weekly.spine.length).toBe(30)
    expect(weekly.spine[0]).toBe('2025-10-06T00:00:00')
    expect(weekly.bands.map((b) => b.key)).toEqual(BANDS.map((b) => b.key))
    const po = weekly.spine.indexOf(`${PO}T00:00:00`)
    expect(weekly.bands.find((b) => b.key === 'rest')!.n[po]).toBe(1)
    expect(weekly.totals[po]).toBe(161)
    expect(weekly.totals[0]).toBe(3)
    expect(weekly.phases[po]).toBe('playoffs')
    expect(weekly.runs.map((r) => r.phase)).toEqual(['regular', 'playoffs'])
    expect(weekly.runs[1]).toEqual({ phase: 'playoffs', from: weekly.spine.indexOf('2026-04-13T00:00:00'), to: 29 })
  })

  it('writes the lede, the tiles and the big-room sentence from the split', () => {
    expect(roomsLede(split)).toMatch(/^In the playoffs, comments about players went from 35\.0% to 53\.1% negative\. About .* of that is game threads taking over the conversation; the rest is every big room getting more negative\.$/)
    const tiles = roomTiles(split)
    expect(tiles.map((t) => t.key)).toEqual(['rise', 'mix', 'harsh'])
    expect(tiles[0]).toMatchObject({ figure: '35.0 → 53.1', unit: null, sub: '200 and 160 comments about players under a post whose room is known.' })
    expect(tiles[1]!.unit).toBe(`of the ${(split.lift * 100).toFixed(1)} pts`)
    expect(tiles[1]!.sub).toBe('Into harsher rooms: game threads went from 50% of the comments to 63%. Each room held at its regular-season tone.')
    expect(tiles[2]!.sub).toBe('Every big room got more negative. The crowd held at its regular-season spread.')
    expect(bigRoomsMoved({ ...split, rooms: split.rooms.map((r) => (r.key === 'general' ? { ...r, harsh: -0.01 } : r)) })).toBe('Every big room got more negative except front page.')
  })

  it('does not credit the crowd when the rise is nothing', () => {
    const flat = roomSplit([roomWeek('general', RS, 30, 50, 20), roomWeek('general', PO, 30, 50, 20)], cal)
    expect(roomsLede(flat)).toBe("In the playoffs, comments about players went from 30.0% to 30.0% negative. The crowd's move between rooms does not explain it.")
  })
})

describe('fraction, fmtShare, fmtPts', () => {
  it('names the nearest common fraction', () => {
    expect(fraction(0.33)).toBe('a third')
    expect(fraction(0.48)).toBe('half')
    expect(fraction(0.7)).toBe('two thirds')
  })

  it('gives a small share the precision it needs', () => {
    expect(fmtShare(0.462)).toBe('46%')
    expect(fmtShare(0.0101)).toBe('1.0%')
    expect(fmtShare(0.0013)).toBe('0.13%')
  })

  it('prints signed points with a real minus', () => {
    expect(fmtPts(0.019)).toBe('+1.9')
    expect(fmtPts(-0.0387)).toBe('−3.9')
    expect(fmtPoints(0.352)).toBe('35.2')
  })
})

describe('playerAngle', () => {
  const qualified = new Set(['Harsh One', 'Harsh Two', 'Kind One', 'Thin', 'Flat'])
  const slug = new Map([...qualified].map((n) => [n, n.toLowerCase().replace(' ', '-')]))
  const rows = [
    playerRoom('Harsh One', 'game_thread', 60, 20, 20),
    playerRoom('Harsh One', 'general', 40, 30, 30),
    playerRoom('Harsh Two', 'game_thread', 50, 30, 20),
    playerRoom('Harsh Two', 'general', 45, 30, 25),
    playerRoom('Kind One', 'game_thread', 30, 40, 30),
    playerRoom('Kind One', 'general', 50, 30, 20),
    playerRoom('Flat', 'game_thread', 40, 30, 30),
    playerRoom('Flat', 'general', 38, 30, 32),
    // Under the room floor in the game thread.
    playerRoom('Thin', 'game_thread', 5, 2, 2),
    playerRoom('Thin', 'general', 50, 30, 20),
    // Not qualified.
    playerRoom('Nobody', 'game_thread', 90, 5, 5),
    playerRoom('Nobody', 'general', 10, 45, 45),
    playerRoom('Harsh One', 'news', 90, 5, 5),
  ]
  const angle = playerAngle(rows, qualified, slug, 20)

  it('compares the qualified players with both rooms at the floor', () => {
    expect(angle).toMatchObject({ qualified: 5, compared: 4, harsher: 3 })
    expect(angle.median).toBeCloseTo((0.02 + 0.05) / 2, 12)
    expect(angle.exceptions.map((g) => g.name)).toEqual(['Kind One'])
    expect(angle.exceptions[0]!.gap).toBeCloseTo(-0.2, 12)
  })

  it('names the exceptions only beyond the gap, the biggest first', () => {
    const wide = playerAngle([...rows, playerRoom('Kind Two', 'game_thread', 10, 45, 45), playerRoom('Kind Two', 'general', 50, 25, 25)], new Set([...qualified, 'Kind Two']), slug, 20)
    expect(wide.exceptions.map((g) => g.name)).toEqual(['Kind Two', 'Kind One'])
    const text = playerAngleText(wide)
    expect(text.lead).toBe('Most players are talked about more harshly in the game thread than on the front page: 3 of the 5 at the official minimum, by a median of 2 points.')
    expect(text.tail).toBe('The exceptions are players whose season was a story more than a schedule: ')
    expect(playerAngleText({ ...wide, harsher: 5, exceptions: [] })).toEqual({ lead: expect.stringMatching(/^Nearly every player is/), exceptions: [], tail: null })
    expect(playerAngleText({ ...wide, compared: 0 }).lead).toBe('No player at the official minimum has both rooms at the floor.')
  })
})

// --- Season arcs ----------------------------------------------------------------

const pt = (net: number): ArcPoint => ({ counts: { neg: 0, neu: 0, pos: 0, total: 1000 }, net })
const march = () => 'March'

describe('timing', () => {
  it('reads an arc with no playoff point off the regular season', () => {
    expect(timing(pt(-0.2), pt(0.1), pt(0.1), null, march)).toBe('Rose through the regular season')
    expect(timing(pt(0.2), pt(-0.1), null, null, march)).toBe('Fell through the regular season')
  })

  it('names the playoffs when the late regular season is under the floor', () => {
    expect(timing(pt(-0.2), pt(0.2), null, pt(0.2), march)).toBe('Turned in the playoffs')
  })

  it('names the span that carried two thirds of the move', () => {
    expect(timing(pt(-0.2), pt(0.2), pt(-0.15), pt(0.2), march)).toBe('Turned in the playoffs')
    expect(timing(pt(-0.2), pt(0.15), pt(0.2), pt(0.18), march)).toBe('Turned in March, held through the playoffs')
    expect(timing(pt(-0.2), pt(0.15), pt(0.2), pt(0.15), march)).toBe('Turned in March, slipped back in the playoffs')
    expect(timing(pt(0.2), pt(-0.15), pt(-0.2), pt(-0.15), march)).toBe('Turned in March, recovered in the playoffs')
  })

  it('reads a steady move as all season, and a mixed one by its playoff half', () => {
    expect(timing(pt(0), pt(0.3), pt(0.15), pt(0.3), march)).toBe('Rose all season')
    expect(timing(pt(0.3), pt(0), pt(0.15), pt(0), march)).toBe('Fell all season')
    expect(timing(pt(0), pt(0.1), pt(-0.1), pt(0.1), march)).toBe('Turned in the playoffs')
    expect(timing(pt(0), pt(0.05), pt(0.03), pt(0.02), march)).toBe('Turned in March')
  })
})

const playoff = (round: number | null) => game('p', '2026-05-01', { season_type: 'playoffs', playoff_round: round })

describe('endedAs', () => {
  it('reads the calendar first, then the round of his last game', () => {
    expect(endedAs('2026-03-19', null, cal)).toBe('Cut short')
    expect(endedAs('2026-04-07', null, cal)).toBe('Season end')
    expect(endedAs('2026-04-12', null, cal)).toBe('Season end')
    expect(endedAs('2026-04-15', game('x', '2026-04-15', { season_type: 'play_in' }), cal)).toBe('Play-in')
    expect(endedAs('2026-05-01', playoff(1), cal)).toBe('First round')
    expect(endedAs('2026-05-01', playoff(2), cal)).toBe('Second round')
    expect(endedAs('2026-05-01', playoff(3), cal)).toBe('Conference finals')
    expect(endedAs('2026-06-13', playoff(4), cal)).toBe('Finals run')
    expect(endedAs('2026-05-01', playoff(null), cal)).toBe('Playoffs')
    expect(endedAs('2026-05-01', null, cal)).toBe('Playoffs')
  })
})

const mondays = (from: string, n: number) => Array.from({ length: n }, (_, i) => plusDays(from, 7 * i))
const rows = (name: string, weeks: readonly string[], neg: number, neu: number, pos: number) => weeks.map((w) => temporal(name, w, neg, neu, pos))

describe('arcField', () => {
  const EARLY = mondays('2025-10-20', 8)
  const LATE_RS = mondays('2026-02-23', 8)
  const GAMES = [
    game('open', '2025-10-21'),
    game('nov', '2025-11-30'),
    game('mar', '2026-03-19'),
    game('apr', '2026-04-12'),
    game('pin', '2026-04-15', { season_type: 'play_in' }),
    game('fin', '2026-06-13', { season_type: 'playoffs', playoff_round: 4, playoff_game: 5 }),
  ]
  const PLAYERS = [player('Finals Star'), player('Faller', { roster_team: 'Dallas Mavericks' }), player('Cut'), player('Early Exit'), player('Thin'), player('Play-in Guy', { roster_team: null }), player('Nobody')]
  const inputs: ArcInputs = {
    temporal: [
      ...rows('Finals Star', EARLY, 60, 50, 40),
      ...rows('Finals Star', LATE_RS, 60, 50, 40),
      ...rows('Finals Star', mondays('2026-04-20', 8), 30, 50, 70),
      ...rows('Faller', EARLY, 30, 50, 70),
      ...rows('Faller', mondays('2026-02-16', 8), 70, 50, 30),
      ...rows('Cut', EARLY, 50, 50, 50),
      ...rows('Cut', mondays('2026-01-26', 8), 49, 50, 51),
      ...rows('Early Exit', EARLY, 50, 50, 50),
      ...rows('Thin', EARLY, 50, 50, 50),
      ...rows('Thin', mondays('2026-04-20', 8), 5, 5, 5),
      ...rows('Play-in Guy', EARLY, 50, 50, 50),
      ...rows('Play-in Guy', mondays('2026-02-23', 8), 50, 50, 50),
      ...rows('Nobody', EARLY, 50, 50, 50),
      ...rows('Nobody', mondays('2026-04-20', 8), 50, 50, 50),
    ],
    playerGames: [
      playerGame('Finals Star', 'open'),
      playerGame('Finals Star', 'fin'),
      playerGame('Faller', 'apr'),
      playerGame('Cut', 'mar'),
      playerGame('Early Exit', 'nov'),
      playerGame('Thin', 'fin'),
      playerGame('Play-in Guy', 'pin'),
      playerGame('Nobody', 'fin'),
    ],
    games: GAMES,
    players: PLAYERS,
    teams: TEAMS,
    qualified: new Set(['Finals Star', 'Faller', 'Cut', 'Early Exit', 'Thin', 'Play-in Guy']),
  }
  const field = arcField(inputs, cal)
  const by = (name: string) => field.find((a) => a.name === name)!

  it('keeps the qualified players with both windows at the floor and no overlap', () => {
    expect(field.map((a) => a.name)).toEqual(['Cut', 'Faller', 'Finals Star', 'Play-in Guy'])
  })

  it('ends the late window at his last game and reads the playoff weeks out of it', () => {
    const star = by('Finals Star')
    expect(star).toMatchObject({ team: 'SAS', ended: 'Finals run', to: '2026-06-13', timing: 'Turned in the playoffs' })
    expect(star.early.counts.total).toBe(1200)
    expect(star.early.net).toBeCloseTo(-20 / 150, 12)
    expect(star.late.net).toBeCloseTo(40 / 150, 12)
    expect(star.lateRs?.net).toBeCloseTo(-20 / 150, 12)
    expect(star.po?.counts.total).toBe(1200)
    expect(star.delta).toBeCloseTo(60 / 150, 12)
  })

  it('has no playoff point for a season that ended in April', () => {
    expect(by('Faller')).toMatchObject({ team: 'DAL', ended: 'Season end', to: '2026-04-12', po: null, timing: 'Fell through the regular season' })
    expect(by('Faller').late.counts.total).toBe(1200)
    expect(by('Cut')).toMatchObject({ ended: 'Cut short', to: '2026-03-19', lateRs: null, po: null })
    expect(by('Play-in Guy')).toMatchObject({ team: '', ended: 'Play-in', to: '2026-04-15' })
  })

  it('ranks the lists and writes the lede', () => {
    const lists = arcLists(field)
    expect(lists.rose.map((a) => a.name)).toEqual(['Finals Star', 'Cut', 'Play-in Guy', 'Faller'])
    expect(lists.fell.map((a) => a.name)).toEqual(['Faller', 'Play-in Guy', 'Cut', 'Finals Star'])
    expect(lists.flat.map((a) => a.name)).toEqual(['Play-in Guy', 'Cut', 'Finals Star', 'Faller'])
    expect(lists.field).toBe(4)
    expect(arcsLede(lists)).toBe(
      'Finals Star won r/NBA over more than anyone: his net sentiment went from 13 points negative in his first 8 weeks to 27 positive in his last 8, among the 4 players measured. Faller fell the furthest, 53 points, and his last 8 weeks ended with the regular season.',
    )
    expect(arcsLede(arcLists([]))).toBe('Too few players clear both windows to measure an arc.')
  })

  it('phrases how a fall ended', () => {
    const lists = arcLists(field)
    const fell = (ended: string) => arcsLede({ ...lists, fell: [{ ...lists.fell[0]!, ended }] })
    expect(fell('Finals run')).toContain('his last 8 weeks were a Finals run.')
    expect(fell('Cut short')).toContain('his last 8 weeks ended early.')
    expect(fell('Second round')).toContain('his last 8 weeks ended in the second round.')
  })

  it('rounds the axis out to ten points and speaks a row', () => {
    expect(arcDomain(field)).toEqual({ lo: -0.3, hi: 0.3, ticks: [-0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3] })
    expect(arcDomain([])).toMatchObject({ lo: -0.5, hi: 0.5 })
    expect(arcText(by('Finals Star'))).toBe('Finals Star: net sentiment −13 in his first 8 weeks, +27 in his last 8; turned in the playoffs.')
  })
})

// --- The loudest threads ----------------------------------------------------------

describe('loudestThreads', () => {
  const GAMES = [
    game('open', '2025-10-21', { home_team: 'Oklahoma City Thunder', away_team: 'Dallas Mavericks', winner: 'Oklahoma City Thunder', home_score: 120, away_score: 100 }),
    game('xmas', '2025-12-25'),
    game('cup', '2025-12-16', { nba_cup_final: true, home_team: 'San Antonio Spurs', away_team: 'New York Knicks', winner: 'San Antonio Spurs' }),
    game('reg', '2026-01-10'),
    game('pin', '2026-04-15', { season_type: 'play_in' }),
    game('wcf1', '2026-05-18', { season_type: 'playoffs', playoff_round: 3, playoff_game: 1 }),
    game('fin5', '2026-06-13', { season_type: 'playoffs', playoff_round: 4, playoff_game: 5, home_team: 'San Antonio Spurs', away_team: 'New York Knicks', winner: 'San Antonio Spurs', home_score: 101, away_score: 99 }),
    game('r1', '2026-04-20', { season_type: 'playoffs', playoff_round: 1, playoff_game: 2 }),
  ]
  const inputs: ThreadInputs = {
    sentiment: [
      sentiment('Wemby', 'wcf1', 1330, 4000, 1453),
      sentiment('Shai', 'wcf1', 1622, 800, 424),
      sentiment('Castle', 'wcf1', 300, 150, 50),
      sentiment('Fox', 'fin5', 3520, 1000, 487),
      sentiment('Wemby', 'fin5', 1000, 2000, 1000),
      sentiment('Wemby', 'r1', 100, 100, 100),
      sentiment('Shai', 'pin', 200, 100, 100),
      sentiment('Durant', 'open', 500, 700, 249),
      sentiment('Sheppard', 'open', 500, 132, 100),
      sentiment('Wemby', 'cup', 300, 400, 186),
      sentiment('Wemby', 'xmas', 200, 200, 200),
      sentiment('Wemby', 'reg', 50, 50, 50),
    ],
    posts: [post('wcf1', 'game_thread', 40000), post('wcf1', 'post_game_thread', 13003), post('fin5', 'game_thread', 56307), post('open', 'game_thread', 20023), post('open', 'discussion', 999), post(null, 'game_thread', 5)],
    games: GAMES,
    players: [player('Wemby'), player('Shai'), player('Castle'), player('Fox'), player('Durant'), player('Sheppard')],
    teams: TEAMS,
    recaps: {
      '0042500311-wemby': { game_id: 'wcf1', attributed_player: 'Wemby' } as RecapEntry,
      '0042500311-castle': { game_id: 'wcf1', attributed_player: 'Castle' } as RecapEntry,
      '0022500001-durant': { game_id: 'open', attributed_player: 'Durant' } as RecapEntry,
    },
  }
  const po = loudestThreads(inputs, cal, true)
  const rs = loudestThreads(inputs, cal, false)

  it('ranks each side of the play-in by comments about players, the play-in with the playoffs', () => {
    expect(po.map((t) => t.gameId)).toEqual(['wcf1', 'fin5', 'pin', 'r1'])
    expect(rs.map((t) => t.gameId)).toEqual(['open', 'cup', 'xmas', 'reg'])
    expect(po[0]!.counts).toEqual({ neg: 3252, neu: 4950, pos: 1927, total: 10129 })
  })

  it('counts Reddit’s comments across both threads, null when the posts are not bridged', () => {
    expect(po[0]!.reddit).toBe(53003)
    expect(rs[0]!.reddit).toBe(20023)
    expect(po[2]!.reddit).toBeNull()
  })

  it('names the thread’s player and a second only by the rule', () => {
    const wcf = po[0]!
    expect(wcf.top).toMatchObject({ name: 'Wemby', slug: 'wemby', counts: { total: 6783 } })
    // Shai: 57.0% on 2,846 against the thread's 32.1%, over the gap; Castle is under the floor.
    expect(wcf.second?.name).toBe('Shai')
    expect(po[1]!.second).toBeNull()
    expect(rs[0]!.second?.name).toBe('Sheppard')
  })

  const at = (n: number, neg: number) => loudestThreads({ ...inputs, sentiment: [sentiment('Lead', 'reg', 500, 500, 0), sentiment('Other', 'reg', neg, n - neg, 0)] }, cal, false)[0]!.second

  it('holds the second name to its floor and its gap exactly', () => {
    // The thread: (500 + neg) / (1000 + n). At n = 500, neg = 400: thread 60.0%, Other 80.0%: a gap of 20 exactly.
    expect(at(500, 400)?.name).toBe('Other')
    expect(at(499, 400)).toBeNull()
    expect(at(500, 399)).toBeNull()
  })

  it('reads the stage from the round, the flag, the calendar or the phase', () => {
    expect(po.map((t) => t.stage)).toEqual(['West Finals · Game 1', 'NBA Finals · Game 5', 'Play-in', 'First round · Game 2'])
    expect(rs.map((t) => t.stage)).toEqual(['Opening night', 'NBA Cup final', 'Christmas', 'Regular season'])
  })

  it('carries the game line with the winner, and every recap of the game', () => {
    expect(po[0]!.line).toMatchObject({ away: { abbr: 'SAS', score: 110, won: true }, home: { abbr: 'OKC', score: 100, won: false }, date: 'May 18' })
    expect(po[0]!.recaps).toEqual([
      { key: '0042500311-wemby', name: 'Wemby' },
      { key: '0042500311-castle', name: 'Castle' },
    ])
    expect(po[1]!.recaps).toEqual([])
    expect(recapsByGame(inputs.recaps).get('open')).toEqual([{ key: '0022500001-durant', name: 'Durant' }])
  })

  it('speaks a thread', () => {
    expect(threadFigure(po[0]!.top)).toBe('19.6% negative on 6,783')
    expect(threadText(po[0]!)).toBe('West Finals · Game 1 · SAS 110 @ OKC 100 · May 18: 10,129 comments about players of 53,003 in the thread, 32.1% negative, 19.0% positive. Mostly about Wemby, 19.6% negative on 6,783. Shai 57.0% negative on 2,846.')
    expect(threadText(po[2]!)).toBe('Play-in · SAS 110 @ OKC 100 · Apr 15: 400 comments about players, 50.0% negative, 25.0% positive. Mostly about Shai, 50.0% negative on 400.')
  })
})
