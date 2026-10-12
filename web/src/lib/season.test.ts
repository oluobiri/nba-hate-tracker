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
  warmestNote,
} from './season'
import { CAL, TEAMS, daily, game, nightsFrom, sentiment } from './season.fixture'

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
