import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { PALETTE } from './palette'

const tokens = readFileSync(path.resolve(__dirname, '../styles/tokens.css'), 'utf8')
const frame = readFileSync(path.resolve(__dirname, 'frame.tsx'), 'utf8')

const token = (name: string): string => {
  const m = tokens.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6});`))
  if (!m) throw new Error(`no token --${name}`)
  return m[1]!
}

// bone2 → --bone-2
const tokenName = (key: string): string => key.replace(/(\d)$/, '-$1')

describe('card palette', () => {
  it('matches tokens.css value for value', () => {
    for (const [key, value] of Object.entries(PALETTE)) expect(value, key).toBe(token(tokenName(key)))
  })

  it('is the only place the frame gets a colour from', () => {
    expect(frame.match(/#[0-9a-f]{6}\b/gi)).toBeNull()
  })
})
