import { describe, expect, it } from 'vitest'

import { parseViewState, serializeViewState } from './url'

const defaults = { threshold: 4321 }

describe('parseViewState', () => {
  it('falls back to defaults for missing or invalid values', () => {
    expect(parseViewState('', defaults)).toEqual({ lens: 'neg', tab: 'neg', n: 4321, all: false })
    expect(parseViewState('?lens=bogus&tab=x&n=-3', defaults)).toEqual({ lens: 'neg', tab: 'neg', n: 4321, all: false })
  })

  it('reads every field', () => {
    expect(parseViewState('?lens=pos&tab=neu&n=250&all=1', defaults)).toEqual({ lens: 'pos', tab: 'neu', n: 250, all: true })
  })
})

describe('serializeViewState', () => {
  it('omits defaults and round-trips the rest', () => {
    expect(serializeViewState({ lens: 'neg', tab: 'neg', n: 4321, all: false }, defaults)).toBe('')
    const s = { lens: 'polar' as const, tab: 'pos' as const, n: 99, all: true }
    const q = serializeViewState(s, defaults)
    expect(q).toBe('?lens=polar&tab=pos&n=99&all=1')
    expect(parseViewState(q, defaults)).toEqual(s)
  })
})
