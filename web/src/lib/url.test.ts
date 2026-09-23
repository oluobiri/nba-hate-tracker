import { describe, expect, it } from 'vitest'

import { GAME_KEYS, RECEIPT_KEYS, parseViewState, serializeViewState, type ViewState } from './url'

const defaults = { threshold: 4321 }
const DEFAULT: ViewState = { lens: 'neg', tab: 'neg', n: 4321, all: false, games: 'talked', log: 'top' }

describe('parseViewState', () => {
  it('falls back to defaults for missing or invalid values', () => {
    expect(parseViewState('', defaults)).toEqual(DEFAULT)
    expect(parseViewState('?lens=bogus&tab=x&n=-3&games=some&log=5', defaults)).toEqual(DEFAULT)
  })

  it('reads every field', () => {
    expect(parseViewState('?lens=pos&tab=neu&n=250&all=1&games=all&log=all', defaults)).toEqual({
      lens: 'pos',
      tab: 'neu',
      n: 250,
      all: true,
      games: 'all',
      log: 'all',
    })
  })

  it('keeps the receipts expansion and the log expansion independent', () => {
    expect(parseViewState('?all=1', defaults)).toMatchObject({ all: true, log: 'top' })
    expect(parseViewState('?log=all', defaults)).toMatchObject({ all: false, log: 'all' })
  })
})

describe('serializeViewState', () => {
  it('omits defaults and round-trips the rest', () => {
    expect(serializeViewState(DEFAULT, defaults)).toBe('')
    const s: ViewState = { lens: 'polar', tab: 'pos', n: 99, all: true, games: 'all', log: 'all' }
    const q = serializeViewState(s, defaults)
    expect(q).toBe('?lens=polar&tab=pos&n=99&all=1&games=all&log=all')
    expect(parseViewState(q, defaults)).toEqual(s)
  })

  it('serialises a game-log view without touching the receipts keys', () => {
    expect(serializeViewState({ ...DEFAULT, games: 'all', log: 'all' }, defaults)).toBe('?games=all&log=all')
  })
})

describe('island key sets', () => {
  it('are disjoint and each key is one the serialiser can emit', () => {
    expect(RECEIPT_KEYS.filter((k) => GAME_KEYS.includes(k))).toEqual([])
    const everything: ViewState = { lens: 'polar', tab: 'pos', n: 1, all: true, games: 'all', log: 'all' }
    const emitted = new Set(new URLSearchParams(serializeViewState(everything, defaults)).keys())
    for (const k of [...RECEIPT_KEYS, ...GAME_KEYS]) expect(emitted.has(k), k).toBe(true)
  })
})
