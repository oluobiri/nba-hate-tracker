import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

// HTML first: an island needs browser state as its reason, and the list of
// islands is a decision, not a drift. Adding one means adding it here.
const ROOT = path.resolve(__dirname)
const ISLANDS = ['FanbaseIndex client:visible', 'Leaderboard client:load', 'PlayerSearch client:idle']

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name)
    return statSync(full).isDirectory() ? walk(full) : [full]
  })
}

describe('islands', () => {
  it('are exactly the declared ones', () => {
    const found = walk(ROOT)
      .filter((f) => f.endsWith('.astro'))
      .flatMap((f) => [...readFileSync(f, 'utf8').matchAll(/<(\w+)\s+(client:\w+)/g)].map((m) => `${m[1]} ${m[2]}`))
      .toSorted()
    expect(found).toEqual(ISLANDS)
  })
})
