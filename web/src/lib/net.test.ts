import { describe, expect, it } from 'vitest'

import { fmtNet, netColor, netOf, netTone } from './net'

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
