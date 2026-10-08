import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { MARKS } from './BrandMark'

// The publish paths on the diagram are drawn in the S3 mark's green from a
// CSS token; the mark itself carries the brand colour as a literal. This pins
// the two together.
const tokens = readFileSync(path.resolve(__dirname, '../styles/tokens.css'), 'utf8')

describe('brand marks', () => {
  it('draw the publish paths in the S3 green', () => {
    const m = tokens.match(/--pub:\s*(#[0-9a-f]{6});/)
    expect(m?.[1]?.toLowerCase()).toBe(MARKS.s3.color.toLowerCase())
  })

  it('are 24-unit paths with a colour each', () => {
    for (const [name, mark] of Object.entries(MARKS)) {
      expect(mark.path, name).toMatch(/^[Mm]/)
      expect(mark.color, name).toMatch(/^#[0-9A-Fa-f]{6}$/)
    }
  })
})
