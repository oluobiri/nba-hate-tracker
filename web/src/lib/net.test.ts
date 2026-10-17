import { describe, expect, it } from 'vitest'

import { fmtNet, netColor, netOf, netTone, playerNetColor, playerNetRange } from './net'

describe('net', () => {
  it('is positive minus negative, null for nothing', () => {
    expect(netOf({ neg: 30, neu: 50, pos: 20, total: 100 })).toBeCloseTo(-0.1, 9)
    expect(netOf({ neg: 0, neu: 0, pos: 0, total: 0 })).toBeNull()
  })

  it('prints signed points with a real minus, a dash for nothing', () => {
    expect(fmtNet(0.12)).toBe('+12')
    expect(fmtNet(-0.3)).toBe('−30')
    expect(fmtNet(0.004)).toBe('0')
    expect(fmtNet(null)).toBe('—')
  })

  it('tones by the printed figure', () => {
    expect(netTone(-0.3)).toBe('neg')
    expect(netTone(0.3)).toBe('pos')
    expect(netTone(0.004)).toBe('neu')
    expect(netTone(null)).toBe('neu')
  })

  it('mixes bone toward heat or ice by the strength, full at ±100, linear', () => {
    expect(netColor(null)).toBe('var(--bone)')
    expect(netColor(0)).toBe('var(--bone)')
    expect(netColor(-0.5)).toBe('color-mix(in srgb, var(--bone), var(--heat) 50%)')
    expect(netColor(1)).toBe('color-mix(in srgb, var(--bone), var(--ice) 100%)')
    expect(netColor(-1.4)).toBe('color-mix(in srgb, var(--bone), var(--heat) 100%)')
  })
})

describe('player net', () => {
  const rows = [
    { neg: 5, neu: 2, pos: 1, total: 8 }, // −50, the floor
    { neg: 1, neu: 4, pos: 3, total: 8 }, // +25, the ceiling
    { neg: 2, neu: 4, pos: 2, total: 8 }, // 0
  ]

  it('takes the range from the lowest and highest player, from counts', () => {
    expect(playerNetRange(rows)).toEqual({ lo: -0.5, hi: 0.25 })
  })

  it('falls back to the game rule on a side with no player past zero, and on nothing', () => {
    expect(playerNetRange(rows.slice(0, 1))).toEqual({ lo: -0.5, hi: 1 })
    expect(playerNetRange(rows.slice(1, 2))).toEqual({ lo: -1, hi: 0.25 })
    expect(playerNetRange([])).toEqual({ lo: -1, hi: 1 })
  })

  it('is full heat at the floor, full ice at the ceiling, bone at zero and at nothing, each side on its own scale', () => {
    const range = { lo: -0.5, hi: 0.25 }
    expect(playerNetColor(null, range)).toBe('var(--bone)')
    expect(playerNetColor(0, range)).toBe('var(--bone)')
    expect(playerNetColor(-0.5, range)).toBe('color-mix(in srgb, var(--bone), var(--heat) 100%)')
    expect(playerNetColor(0.25, range)).toBe('color-mix(in srgb, var(--bone), var(--ice) 100%)')
    expect(playerNetColor(-0.125, range)).toBe('color-mix(in srgb, var(--bone), var(--heat) 25%)')
    expect(playerNetColor(0.125, range)).toBe('color-mix(in srgb, var(--bone), var(--ice) 50%)')
  })

  it('clamps a value past the range', () => {
    const range = { lo: -0.5, hi: 0.25 }
    expect(playerNetColor(-0.9, range)).toBe('color-mix(in srgb, var(--bone), var(--heat) 100%)')
    expect(playerNetColor(0.5, range)).toBe('color-mix(in srgb, var(--bone), var(--ice) 100%)')
  })
})
