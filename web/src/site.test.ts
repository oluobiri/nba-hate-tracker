import { describe, expect, it } from 'vitest'

import { NAV, SEASONS, SITE_INDEXABLE } from './site'

describe('NAV', () => {
  it('follows the brief order and ends every href with a slash', () => {
    expect(NAV.map((n) => n.label)).toEqual([
      'Leaderboard',
      'Fanbases',
      'Season',
      'The Race',
      'Recaps',
      'How it works',
    ])
    for (const n of NAV) expect(n.href.endsWith('/')).toBe(true)
  })
})

describe('SITE_INDEXABLE', () => {
  it('defaults to noindex when the env var is unset', () => {
    expect(process.env.SITE_INDEXABLE).toBeUndefined()
    expect(SITE_INDEXABLE).toBe(false)
  })
})

describe('SEASONS', () => {
  it('lists the published season only', () => {
    expect(SEASONS).toEqual(['2025-26'])
  })
})
