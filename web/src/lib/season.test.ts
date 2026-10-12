import { describe, expect, it } from 'vitest'

import { negRate } from './metrics'
import {
  aboveStretch,
  addDays,
  againstLevel,
  dayLabel,
  extremeNights,
  gameComments,
  gameNightSplit,
  harshestNote,
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
  roomRows,
  roomSplit,
  roomTable,
  roomTiles,
  roomsLede,
  warmestNote,
  weekPhase,
} from './season'
import { CAL, TEAMS, daily, game, nightsFrom, playerRoom, plusDays, roomWeek, sentiment } from './season.fixture'

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
    const daily = split.rooms.find((r) => r.key === 'daily')!
    expect(daily.rateReg).toBeCloseTo(0.5, 12)
    expect(daily.ratePo).toBeCloseTo(0.5, 12)
    expect(daily.harsh).toBe(0)
    expect(daily.mix).toBeGreaterThan(0)
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
