import { describe, expect, it } from 'vitest'

import { PRODUCTION_DATA_BASE, locate, resolveDataBase, seasonLocation } from './env'

describe('resolveDataBase', () => {
  it('defaults to the production URL when DATA_BASE is unset or blank', () => {
    expect(resolveDataBase({})).toBe(PRODUCTION_DATA_BASE)
    expect(resolveDataBase({ DATA_BASE: '  ' })).toBe(PRODUCTION_DATA_BASE)
  })

  it('takes DATA_BASE verbatim otherwise', () => {
    expect(resolveDataBase({ DATA_BASE: '../data' })).toBe('../data')
  })
})

describe('seasonLocation', () => {
  it('uses the published layout for a URL', () => {
    const loc = seasonLocation('2025-26', 'https://example.test/data/')
    expect(loc).toEqual({ kind: 'url', root: 'https://example.test/data/season=2025-26' })
    expect(locate(loc, 'manifest.json')).toBe('https://example.test/data/season=2025-26/manifest.json')
  })

  it('uses the local layout for a path', () => {
    const loc = seasonLocation('2025-26', '/repo/data')
    expect(loc.kind).toBe('file')
    expect(loc.root).toBe('/repo/data/2025-26/dashboard')
    expect(locate(loc, 'manifest.json')).toBe('/repo/data/2025-26/dashboard/manifest.json')
  })
})
