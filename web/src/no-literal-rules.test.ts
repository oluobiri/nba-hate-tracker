import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

// Rule numbers come from the manifest; none is typed into site code. The
// snapshot is the contract itself and the only file allowed to carry them.
const ROOT = path.resolve(__dirname)
const ALLOWED = new Set(['data/schema.json'])
const LITERALS = /\b5[,.]?000\b/

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name)
    return statSync(full).isDirectory() ? walk(full) : [full]
  })
}

describe('rule numbers', () => {
  it('never appear as literals in src/', () => {
    const offenders = walk(ROOT)
      .filter((f) => !f.endsWith('.test.ts'))
      .filter((f) => !ALLOWED.has(path.relative(ROOT, f)))
      .filter((f) => LITERALS.test(readFileSync(f, 'utf8')))
      .map((f) => path.relative(ROOT, f))
    expect(offenders).toEqual([])
  })
})
