import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

// The favicon is a standalone file and cannot read CSS, so it carries the
// token values as literals. This pins them: a token change fails here until
// the favicon follows. The header reuses the same file, so it follows too.
const favicon = readFileSync(path.resolve(__dirname, '../public/favicon.svg'), 'utf8')
const tokens = readFileSync(path.resolve(__dirname, 'styles/tokens.css'), 'utf8')

const token = (name: string): string => {
  const m = tokens.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6});`))
  if (!m) throw new Error(`no token --${name}`)
  return m[1]!
}

describe('favicon.svg', () => {
  it('uses exactly the ink, heat, neutral and ice tokens', () => {
    const used = new Set(favicon.match(/#[0-9a-f]{6}\b/g))
    expect(used).toEqual(new Set(['ink', 'heat', 'neu', 'ice'].map(token)))
  })
})
