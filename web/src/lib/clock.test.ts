import { describe, expect, it } from 'vitest'

import {
  BREAK_CARD,
  breakLabel,
  buildTimeline,
  defaultSpeed,
  durationSeconds,
  etTime,
  fromPlayback,
  gameClock,
  phaseAt,
  playCursor,
  playStamp,
  speedPhrase,
  stoppageAt,
  stoppageLabel,
  toPlayback,
  wallStamp,
} from './clock'
import { OVERTIME, period, play, REGULATION } from './replay.fixture'

describe('buildTimeline', () => {
  const tl = buildTimeline(REGULATION)

  it('spans tip to buzzer in wall seconds and compresses each break to one card', () => {
    expect(tl.tip).toBe(1000)
    expect(tl.buzzer).toBe(6400)
    expect(tl.total).toBe(5400)
    expect(tl.segments.map((s) => s.kind)).toEqual(['period', 'break', 'period', 'break', 'period', 'break', 'period'])
    expect(tl.segments.filter((s) => s.kind === 'break').map((s) => s.p1 - s.p0)).toEqual([BREAK_CARD, BREAK_CARD, BREAK_CARD])
    expect(tl.segments.filter((s) => s.kind === 'break').map((s) => s.t1 - s.t0)).toEqual([200, 1000, 200])
    expect(tl.length).toBe(4000 + 3 * BREAK_CARD)
  })

  it('labels the periods and the breaks', () => {
    expect(tl.periods.map((p) => p.label)).toEqual(['Q1', 'Q2', 'Q3', 'Q4'])
    expect(tl.segments.map((s) => s.label)).toEqual(['Q1', 'End of 1st', 'Q2', 'Halftime', 'Q3', 'End of 3rd', 'Q4'])
    const ot = buildTimeline(OVERTIME)
    expect(ot.periods.map((p) => p.label)).toEqual(['Q1', 'Q2', 'Q3', 'Q4', 'OT1', 'OT2'])
    expect(breakLabel(4)).toBe('End of 4th')
    expect(breakLabel(5)).toBe('End of 1st overtime')
  })

  it('reads the frame in any order and refuses one the clock cannot run on', () => {
    expect(buildTimeline(REGULATION.toReversed()).length).toBe(tl.length)
    expect(() => buildTimeline([])).toThrow('periods: empty')
    expect(() => buildTimeline([period(1, 1000, 2000), period(3, 2200, 3200)])).toThrow('periods: 3 where 2 was expected')
    expect(() => buildTimeline([period(1, 2000, 1000)])).toThrow('Q1 ends before it starts')
    expect(() => buildTimeline([period(1, 1000, 2000), period(2, 1900, 3000)])).toThrow('Q2 starts before Q1 ends')
  })
})

describe('toPlayback and fromPlayback', () => {
  const tl = buildTimeline(REGULATION)

  it('are linear inside a period and round-trip its every second', () => {
    expect(toPlayback(tl, 0)).toBe(0)
    expect(toPlayback(tl, 500)).toBe(500)
    expect(toPlayback(tl, 1200)).toBe(1000 + BREAK_CARD)
    for (const t of [0, 1, 999, 1000, 1200, 3200, 4400, 5400]) expect(fromPlayback(tl, toPlayback(tl, t))).toBe(t)
  })

  it("give a period both its marker seconds, and a break the seconds between", () => {
    expect(toPlayback(tl, 2200)).toBe(2000 + BREAK_CARD)
    expect(toPlayback(tl, 3200)).toBe(2000 + 2 * BREAK_CARD)
    const mid = toPlayback(tl, 2700)
    expect(mid).toBeGreaterThan(2000 + BREAK_CARD)
    expect(mid).toBeLessThan(2000 + 2 * BREAK_CARD)
    expect(fromPlayback(tl, mid)).toBe(2700)
  })

  it('clamp to the game', () => {
    expect(toPlayback(tl, -50)).toBe(0)
    expect(toPlayback(tl, 9999)).toBe(tl.length)
    expect(fromPlayback(tl, -1)).toBe(0)
    expect(fromPlayback(tl, tl.length + 5)).toBe(tl.total)
  })
})

describe('phaseAt', () => {
  const tl = buildTimeline(REGULATION)

  it('names the pregame, a period, a break and the final', () => {
    expect(phaseAt(tl, -5)).toMatchObject({ phase: 'pre', period: 0, label: 'Pregame' })
    expect(phaseAt(tl, 3300)).toMatchObject({ phase: 'live', period: 3, label: 'Q3' })
    expect(phaseAt(tl, 2700)).toMatchObject({ phase: 'break', period: 2, label: 'Halftime' })
    expect(phaseAt(tl, 1000)).toMatchObject({ phase: 'live', period: 1 })
    expect(phaseAt(tl, 6000)).toMatchObject({ phase: 'post', period: 4, label: 'Final' })
  })
})

describe('playCursor', () => {
  const tl = buildTimeline(REGULATION)
  const plays = [play({ wall_clock: 1000 }), play({ wall_clock: 1050 }), play({ wall_clock: 1300 })]

  it('is the last play logged at or before t', () => {
    expect(playCursor(plays, tl, -1)).toBe(-1)
    expect(playCursor(plays, tl, 0)).toBe(0)
    expect(playCursor(plays, tl, 49)).toBe(0)
    expect(playCursor(plays, tl, 50)).toBe(1)
    expect(playCursor(plays, tl, 5000)).toBe(2)
  })
})

describe('gameClock and playStamp', () => {
  it('reads the feed clock as minutes and seconds', () => {
    expect(gameClock('PT11M35.00S')).toBe('11:35')
    expect(gameClock('PT05M00.00S')).toBe('05:00')
    expect(gameClock('PT00M00.00S')).toBe('00:00')
    expect(gameClock('PT0M9.5S')).toBe('00:09')
    expect(gameClock('nope')).toBe('--:--')
    expect(playStamp({ period: 5, clock: 'PT04M12.00S' })).toBe('OT1 04:12')
  })
})

describe('stoppageAt and stoppageLabel', () => {
  const tl = buildTimeline(REGULATION.slice(0, 2))
  const plays = [
    play({ kind: 'period_start', period: 1, game_seconds: 0 }),
    play({ kind: 'shot', game_seconds: 25 }),
    play({ kind: 'timeout', game_seconds: 369, team_tricode: 'SAS' }),
    play({ kind: 'sub_out', game_seconds: 369 }),
    play({ kind: 'free_throw', game_seconds: 369 }),
    play({ kind: 'shot', game_seconds: 376 }),
    play({ kind: 'period_end', period: 1, game_seconds: 720 }),
    play({ kind: 'period_start', period: 2, game_seconds: 720 }),
    play({ kind: 'shot', period: 2, game_seconds: 730 }),
    play({ kind: 'period_end', period: 2, game_seconds: 1440 }),
  ]
  const label = (cursor: number) => stoppageLabel(stoppageAt(plays, cursor, tl))

  it('holds a timeout through the substitutions logged on its second, until the ball is back in play', () => {
    expect(label(2)).toBe('TIMEOUT · SAS')
    expect(label(3)).toBe('TIMEOUT · SAS')
    expect(label(4)).toBeNull()
    expect(label(5)).toBeNull()
  })

  it('reads the tip, the end of a period, and the final; a period start clears the last end', () => {
    expect(label(-1)).toBe('TIP')
    expect(label(0)).toBe('TIP')
    expect(label(1)).toBeNull()
    expect(label(6)).toBe('END OF 1ST')
    expect(label(7)).toBeNull()
    expect(label(8)).toBeNull()
    expect(label(9)).toBe('FINAL')
  })

  it('names halftime, the third, an overtime, and a timeout without a team', () => {
    const four = buildTimeline(REGULATION)
    expect(stoppageLabel(stoppageAt([play({ kind: 'period_end', period: 2 })], 0, four))).toBe('HALFTIME')
    expect(stoppageLabel(stoppageAt([play({ kind: 'period_end', period: 3 })], 0, four))).toBe('END OF 3RD')
    const six = buildTimeline(OVERTIME)
    expect(stoppageLabel(stoppageAt([play({ kind: 'period_end', period: 5 })], 0, six))).toBe('END OF OT1')
    expect(stoppageLabel(stoppageAt([play({ kind: 'timeout' })], 0, six))).toBe('TIMEOUT')
  })
})

describe('the speed presets', () => {
  const tl = buildTimeline(REGULATION)

  it('play the whole game in real seconds, and the default lands nearest the target', () => {
    expect(durationSeconds(tl, 30)).toBeCloseTo(4540 / 30)
    expect(defaultSpeed(tl)).toBe(30)
    expect(speedPhrase(tl, 30)).toBe('the game in 3 min')
    expect(speedPhrase(tl, 300)).toBe('the game in 1 min')
  })
})

describe('etTime and wallStamp', () => {
  it('print the wall clock in Eastern time', () => {
    expect(etTime(1781397804)).toBe('8:43 PM ET')
    expect(wallStamp(buildTimeline([period(1, 1781397804, 1781399471)]), 60)).toBe('8:44 PM ET')
  })
})
