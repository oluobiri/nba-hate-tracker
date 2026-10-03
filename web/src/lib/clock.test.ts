import { existsSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { assertRecapDocument } from '../data/recap'
import type { RecapDocument } from '../data/types.gen'
import { CURRENT_SEASON } from '../site'
import { buildTimeline, cardAt, clockAt, etTime, gameClock, GAME_RATE, idxAt, lengthPhrase, mmss, periodStartsU, playCursor, playStamp, POST, PRE, tOfU, uOfT, uOfWall, wallOfU } from './clock'
import { toRows } from './replay'
import { smallGame } from './replay.fixture'

const near = (v: number, want: number) => expect(v).toBeCloseTo(want, 3)

describe('idxAt', () => {
  it('finds the last index at or before x, −1 before the first', () => {
    expect(idxAt([1, 3, 3, 5], 0)).toBe(-1)
    expect(idxAt([1, 3, 3, 5], 1)).toBe(0)
    expect(idxAt([1, 3, 3, 5], 3)).toBe(2)
    expect(idxAt([1, 3, 3, 5], 9)).toBe(3)
    expect(idxAt([], 1)).toBe(-1)
  })
})

describe('buildTimeline on the small game', () => {
  const { periods, plays } = smallGame()
  const tl = buildTimeline(plays, periods)

  it('runs live play at GAME_RATE and starts after the pre-game beat', () => {
    expect(tl.playU[0]).toBe(PRE)
    near(tl.playU[1]!, PRE + 10 / GAME_RATE)
    near(tl.playU[2]!, PRE + 20 / GAME_RATE)
  })

  it('holds a timeout for its card, at least the minimum, before play resumes', () => {
    const timeout = tl.cards.find((c) => c.kind === 'timeout')!
    expect(timeout.label).toBe('TIMEOUT · AAA')
    near(timeout.u0, tl.playU[2]!)
    near(timeout.u1 - timeout.u0, 2.5)
    // the free throw lands when the card lifts; the clock never moved
    near(tl.playU[3]!, timeout.u1)
    expect(clockAt(tl, timeout.u0 + 1).time).toBe(clockAt(tl, tl.playU[3]!).time)
  })

  it('squeezes an ordinary stoppage to a beat, capped, with its own anchor before play resumes', () => {
    // free throw (g 20, wall 1080) → period end (g 720, wall 1800): 20 idle wall seconds = 1/3 s
    const resume = tl.anchors.find((a) => a.wall === 1100)!
    expect(resume.g).toBe(20)
    near(resume.u, tl.playU[3]! + 20 / 60)
    near(tl.playU[4]!, resume.u + 700 / GAME_RATE)
    // the last stoppage of 60 wall seconds is capped at the ordinary beat
    const lastResume = tl.anchors.find((a) => a.wall === 2360)!
    near(lastResume.u, tl.playU[6]! + 9 / 10)
  })

  it('makes the break a card with the clock at 0:00 and the next period starting when it lifts', () => {
    const brk = tl.cards.find((c) => c.kind === 'break')!
    expect(brk.label).toBe('END OF Q1')
    near(brk.u0, tl.playU[4]!)
    near(brk.u1 - brk.u0, 4)
    near(tl.playU[5]!, brk.u1)
    expect(clockAt(tl, brk.u0 + 3)).toEqual({ label: 'END Q1', time: '0:00', period: 1 })
    expect(cardAt(tl, brk.u0 + 3)).toBe(brk)
    expect(cardAt(tl, brk.u1)).toBeNull()
  })

  it('holds a timeout card open through the substitutions stamped on its second', () => {
    const game = smallGame()
    const subs = game.plays.flatMap((p) =>
      p.kind === 'timeout'
        ? [p, { ...p, action_number: 7, kind: 'sub_out', action_type: 'substitution', sub_type: 'out', description: 'SUB out: A. Guard', person_id: 3 }]
        : [p],
    )
    const withSubs = buildTimeline(subs, game.periods)
    const card = withSubs.cards.find((c) => c.kind === 'timeout')!
    near(card.u0, withSubs.playU[2]!)
    near(withSubs.playU[3]!, card.u0)
    near(card.u1 - card.u0, 2.5)
    near(withSubs.playU[4]!, card.u1)
    // the dead minute runs over the card, not after it
    near(uOfWall(withSubs, 1050), card.u0 + 1.25)
  })

  it('ends at the buzzer plus the post-game tail', () => {
    near(tl.endU, tl.playU[7]!)
    near(tl.totalU, tl.endU + POST)
    expect(tl.tip).toBe(1000)
    expect(tl.buzzer).toBe(2800)
    expect(clockAt(tl, tl.endU)).toEqual({ label: 'FINAL', time: '0:00', period: 2 })
    expect(lengthPhrase(tl)).toBe('about 1 min at 1×')
  })

  it('reads the clock between plays and before the tip', () => {
    expect(clockAt(tl, 0)).toEqual({ label: 'Q1', time: '12:00', period: 1 })
    expect(clockAt(tl, tl.playU[1]!)).toEqual({ label: 'Q1', time: '11:50', period: 1 })
    // halfway through the 700 live seconds after the stoppage: 20 + 350 = 370 → 5:50 left
    const resume = tl.anchors.find((a) => a.wall === 1100)!
    expect(clockAt(tl, resume.u + 350 / GAME_RATE)).toEqual({ label: 'Q1', time: '5:50', period: 1 })
    expect(clockAt(tl, tl.playU[6]!)).toEqual({ label: 'Q2', time: '7:20', period: 2 })
  })

  it('maps the wall clock to replay time and back', () => {
    near(uOfWall(tl, 1000), PRE)
    near(uOfWall(tl, 1010), tl.playU[1]!)
    // inside the timeout: the wall runs, u runs over the card
    const timeout = tl.cards.find((c) => c.kind === 'timeout')!
    near(uOfWall(tl, 1050), timeout.u0 + (timeout.u1 - timeout.u0) / 2)
    // the break: wall 1800 → 2000 is the 4 s card
    const brk = tl.cards.find((c) => c.kind === 'break')!
    near(uOfWall(tl, 1900), brk.u0 + 2)
    // outside the game: squeezed and stretched, clamped at the windows
    near(uOfWall(tl, 1000 - 900), PRE / 2)
    expect(uOfWall(tl, 1000 - 99999)).toBe(0)
    near(uOfWall(tl, 2800 + 600), tl.endU + POST / 2)
    near(uOfWall(tl, 2800 + 99999), tl.totalU)
    for (const wall of [1000, 1005, 1050, 1095, 1500, 1900, 2000, 2200, 2500, 2800]) near(wallOfU(tl, uOfWall(tl, wall)), wall)
    for (const t of [0, 60, 777, 1800]) expect(tOfU(tl, uOfT(tl, t))).toBe(t)
  })

  it('finds the play cursor and the period starts', () => {
    expect(playCursor(tl, 0)).toBe(-1)
    expect(playCursor(tl, PRE)).toBe(0)
    expect(playCursor(tl, tl.totalU)).toBe(7)
    expect(periodStartsU(tl)).toEqual([
      { period: 1, u: PRE },
      { period: 2, u: tl.playU[5] },
    ])
  })

  it('refuses an empty game', () => {
    expect(() => buildTimeline([], periods)).toThrow('a timeline needs plays and periods')
  })
})

describe('the clock strings', () => {
  it('reads the feed clock without a leading zero and shrugs at anything else', () => {
    expect(gameClock('PT09M44.00S')).toBe('9:44')
    expect(gameClock('PT12M00.00S')).toBe('12:00')
    expect(gameClock('PT00M01.60S')).toBe('0:01')
    expect(gameClock('late')).toBe('--:--')
    expect(playStamp({ period: 5, clock: 'PT02M30.00S' })).toBe('OT1 2:30')
  })

  it('rounds seconds left up so 0:00 is the buzzer alone', () => {
    expect(mmss(0)).toBe('0:00')
    expect(mmss(0.2)).toBe('0:01')
    expect(mmss(719.5)).toBe('12:00')
    expect(mmss(65)).toBe('1:05')
  })

  it('prints a wall second in New York', () => {
    expect(etTime(1781397804)).toBe('8:43 PM ET')
  })
})

// The published files, when the repo's data directory is beside the site.
const RECAPS = path.resolve(__dirname, '../../../data', CURRENT_SEASON, 'dashboard/recaps')
const files = existsSync(RECAPS) ? readdirSync(RECAPS).filter((f) => f.endsWith('.json')) : []
const load = (file: string): RecapDocument => assertRecapDocument(JSON.parse(readFileSync(path.join(RECAPS, file), 'utf8')), file)

describe.skipIf(files.length === 0)('the live files', () => {
  it.each(files)('%s builds a timeline that only runs forward, one card per timeout and break', (file) => {
    const doc = load(file)
    const plays = toRows(doc.frames.plays)
    const periods = toRows(doc.frames.periods)
    const tl = buildTimeline(plays, periods)
    for (let i = 1; i < tl.playU.length; i++) expect(tl.playU[i]).toBeGreaterThanOrEqual(tl.playU[i - 1]!)
    for (let i = 1; i < tl.anchors.length; i++) {
      expect(tl.anchors[i]!.u).toBeGreaterThanOrEqual(tl.anchors[i - 1]!.u)
      expect(tl.anchors[i]!.wall).toBeGreaterThanOrEqual(tl.anchors[i - 1]!.wall)
    }
    const timeouts = plays.filter((p) => p.kind === 'timeout').length
    expect(tl.cards.filter((c) => c.kind === 'timeout')).toHaveLength(timeouts)
    expect(tl.cards.filter((c) => c.kind !== 'timeout')).toHaveLength(periods.length - 1)
    expect(tl.cards.find((c) => c.kind === 'halftime')!.u1 - tl.cards.find((c) => c.kind === 'halftime')!.u0).toBe(6)
    expect(periodStartsU(tl).map((p) => p.period)).toEqual(periods.map((p) => p.period))
    expect(tl.tip).toBe(periods[0]!.start_wall)
    expect(tl.buzzer).toBe(periods[periods.length - 1]!.end_wall)
  })

  it.each(files)('%s reads every whole-second play at its own clock and names the overtimes', (file) => {
    const doc = load(file)
    const plays = toRows(doc.frames.plays)
    const periods = toRows(doc.frames.periods)
    const tl = buildTimeline(plays, periods)
    plays.forEach((p, i) => {
      // a play on the buzzer's second shares its u with the break card
      if (p.kind === 'period_end' || !p.clock.endsWith('.00S') || cardAt(tl, tl.playU[i]!)?.kind === 'break' || cardAt(tl, tl.playU[i]!)?.kind === 'halftime') return
      const read = clockAt(tl, tl.playU[i]!)
      expect(read.label, `${file} play ${p.action_number}`).toBe(playStamp(p).split(' ')[0])
      expect(read.time, `${file} play ${p.action_number}`).toBe(gameClock(p.clock))
    })
    const last = periods[periods.length - 1]!.period
    if (last > 4) expect(clockAt(tl, tl.playU[tl.playU.length - 2]!).label).toBe(`OT${last - 4}`)
  })

  it.each(files)('%s holds the clock through every timeout while the wall runs', (file) => {
    const doc = load(file)
    const plays = toRows(doc.frames.plays)
    const tl = buildTimeline(plays, toRows(doc.frames.periods))
    for (const card of tl.cards.filter((c) => c.kind === 'timeout')) {
      expect(clockAt(tl, card.u0).time).toBe(clockAt(tl, card.u1 - 0.01).time)
      expect(wallOfU(tl, card.u1 - 0.01)).toBeGreaterThan(wallOfU(tl, card.u0))
      // the card ends where play resumes: no play lands inside it
      expect(tl.playU.filter((pu) => pu > card.u0 && pu < card.u1)).toHaveLength(0)
    }
  })

  it.each(files)('%s round-trips every comment between the windows through u and t', (file) => {
    const doc = load(file)
    const tl = buildTimeline(toRows(doc.frames.plays), toRows(doc.frames.periods))
    for (const wall of doc.frames.comments.created_utc) {
      if (wall < tl.tip - 30 * 60 || wall > tl.buzzer + 20 * 60) continue
      const u = uOfWall(tl, wall)
      expect(u).toBeGreaterThanOrEqual(0)
      expect(u).toBeLessThanOrEqual(tl.totalU)
      expect(Math.abs(wallOfU(tl, u) - wall)).toBeLessThan(1)
      const t = wall - tl.tip
      if (t >= 0) expect(tOfU(tl, uOfT(tl, t))).toBe(t)
    }
  })
})
