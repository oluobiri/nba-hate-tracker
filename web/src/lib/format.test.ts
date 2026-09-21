import { describe, expect, it } from 'vitest'

import { fmtInt, fmtPct, fmtSigned, ordinal } from './format'

describe('formatters', () => {
  it('render fractions as percentages and integers with separators', () => {
    expect(fmtPct(0.5104)).toBe('51.0%')
    expect(fmtPct(0.5104, 2)).toBe('51.04%')
    expect(fmtInt(53454)).toBe('53,454')
    expect(fmtSigned(0.021)).toBe('+2.1')
    expect(fmtSigned(-0.021)).toBe('-2.1')
  })

  it.each([
    [1, '1st'],
    [2, '2nd'],
    [3, '3rd'],
    [4, '4th'],
    [11, '11th'],
    [12, '12th'],
    [13, '13th'],
    [22, '22nd'],
    [101, '101st'],
  ])('ordinal(%i) is %s', (n, expected) => {
    expect(ordinal(n)).toBe(expected)
  })
})
