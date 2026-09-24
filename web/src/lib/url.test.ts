import { describe, expect, it } from 'vitest'

import { GAME_KEYS, GRID_KEYS, RECEIPT_KEYS, parseViewState, serializeViewState, type ViewState } from './url'

const defaults = { threshold: 4321 }
const DEFAULT: ViewState = { lens: 'neg', tab: 'neg', n: 4321, all: false, games: 'talked', log: 'top', scale: 'delta', min: 0 }
// The grid passes its cell floor; the other islands pass none.
const gridDefaults = { threshold: 4321, min: 250 }

describe('parseViewState', () => {
  it('falls back to defaults for missing or invalid values', () => {
    expect(parseViewState('', defaults)).toEqual(DEFAULT)
    expect(parseViewState('?lens=bogus&tab=x&n=-3&games=some&log=5&scale=huge&min=abc', defaults)).toEqual(DEFAULT)
  })

  it('reads every field', () => {
    expect(parseViewState('?lens=pos&tab=neu&n=250&all=1&games=all&log=all&scale=raw&min=500', defaults)).toEqual({
      lens: 'pos',
      tab: 'neu',
      n: 250,
      all: true,
      games: 'all',
      log: 'all',
      scale: 'raw',
      min: 500,
    })
  })

  it('falls back to the caller\'s cell floor for min', () => {
    expect(parseViewState('', gridDefaults)).toMatchObject({ min: 250 })
    expect(parseViewState('?min=abc', gridDefaults)).toMatchObject({ min: 250 })
    expect(parseViewState('?min=1000', gridDefaults)).toMatchObject({ min: 1000 })
  })

  it('keeps the receipts expansion and the log expansion independent', () => {
    expect(parseViewState('?all=1', defaults)).toMatchObject({ all: true, log: 'top' })
    expect(parseViewState('?log=all', defaults)).toMatchObject({ all: false, log: 'all' })
  })
})

describe('serializeViewState', () => {
  it('omits defaults and round-trips the rest', () => {
    expect(serializeViewState(DEFAULT, defaults)).toBe('')
    const s: ViewState = { lens: 'polar', tab: 'pos', n: 99, all: true, games: 'all', log: 'all', scale: 'raw', min: 7 }
    const q = serializeViewState(s, defaults)
    expect(q).toBe('?lens=polar&tab=pos&n=99&all=1&games=all&log=all&scale=raw&min=7')
    expect(parseViewState(q, defaults)).toEqual(s)
  })

  it('omits min at the cell floor and writes it above', () => {
    expect(serializeViewState({ ...DEFAULT, min: 250 }, gridDefaults)).toBe('')
    expect(serializeViewState({ ...DEFAULT, min: 1000 }, gridDefaults)).toBe('?min=1000')
  })

  it('serialises a game-log view without touching the receipts keys', () => {
    expect(serializeViewState({ ...DEFAULT, games: 'all', log: 'all' }, defaults)).toBe('?games=all&log=all')
  })
})

describe('island key sets', () => {
  it('are disjoint and each key is one the serialiser can emit', () => {
    const sets = [RECEIPT_KEYS, GAME_KEYS, GRID_KEYS]
    for (const a of sets) for (const b of sets) if (a !== b) expect(a.filter((k) => b.includes(k))).toEqual([])
    const everything: ViewState = { lens: 'polar', tab: 'pos', n: 1, all: true, games: 'all', log: 'all', scale: 'raw', min: 1 }
    const emitted = new Set(new URLSearchParams(serializeViewState(everything, defaults)).keys())
    for (const k of sets.flat()) expect(emitted.has(k), k).toBe(true)
  })
})
