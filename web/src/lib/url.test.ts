import { describe, expect, it } from 'vitest'

import { GAME_KEYS, GRID_KEYS, RACE_KEYS, RECEIPT_KEYS, REPLAY_KEYS, parseViewState, serializeViewState, type ViewState } from './url'

const defaults = { threshold: 4321 }
const DEFAULT: ViewState = { lens: 'neg', tab: 'neg', n: 4321, all: false, games: 'talked', log: 'top', scale: 'delta', min: 0, t: null, mode: 'hated', by: 'rate', w: null }
// The grid passes its cell floor; the other islands pass none.
const gridDefaults = { threshold: 4321, min: 250 }

describe('parseViewState', () => {
  it('falls back to defaults for missing or invalid values', () => {
    expect(parseViewState('', defaults)).toEqual(DEFAULT)
    expect(parseViewState('?lens=bogus&tab=x&n=-3&games=some&log=5&scale=huge&min=abc&t=abc&mode=liked&by=sum&w=abc', defaults)).toEqual(DEFAULT)
  })

  it('reads every field', () => {
    expect(parseViewState('?lens=pos&tab=neu&n=250&all=1&games=all&log=all&scale=raw&min=500&t=600&mode=loved&by=count&w=21', defaults)).toEqual({
      lens: 'pos',
      tab: 'neu',
      n: 250,
      all: true,
      games: 'all',
      log: 'all',
      scale: 'raw',
      min: 500,
      t: 600,
      mode: 'loved',
      by: 'count',
      w: 21,
    })
  })

  it('reads the replay moment as a whole non-negative second, or none', () => {
    expect(parseViewState('?t=0', defaults)).toMatchObject({ t: 0 })
    expect(parseViewState('?t=12.6', defaults)).toMatchObject({ t: 13 })
    expect(parseViewState('?t=-5', defaults)).toMatchObject({ t: null })
    expect(parseViewState('?t=', defaults)).toMatchObject({ t: null })
  })

  it('reads the race week as a whole non-negative index, or none', () => {
    expect(parseViewState('?w=0', defaults)).toMatchObject({ w: 0 })
    expect(parseViewState('?w=21', defaults)).toMatchObject({ w: 21 })
    expect(parseViewState('?w=2.5', defaults)).toMatchObject({ w: null })
    expect(parseViewState('?w=-1', defaults)).toMatchObject({ w: null })
    expect(parseViewState('?w=', defaults)).toMatchObject({ w: null })
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
    const s: ViewState = { lens: 'polar', tab: 'pos', n: 99, all: true, games: 'all', log: 'all', scale: 'raw', min: 7, t: 0, mode: 'loved', by: 'count', w: 0 }
    const q = serializeViewState(s, defaults)
    expect(q).toBe('?lens=polar&tab=pos&n=99&all=1&games=all&log=all&scale=raw&min=7&t=0&mode=loved&by=count&w=0')
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
    const sets = [RECEIPT_KEYS, GAME_KEYS, GRID_KEYS, REPLAY_KEYS, RACE_KEYS]
    for (const a of sets) for (const b of sets) if (a !== b) expect(a.filter((k) => b.includes(k))).toEqual([])
    const everything: ViewState = { lens: 'polar', tab: 'pos', n: 1, all: true, games: 'all', log: 'all', scale: 'raw', min: 1, t: 1, mode: 'loved', by: 'count', w: 1 }
    const emitted = new Set(new URLSearchParams(serializeViewState(everything, defaults)).keys())
    for (const k of sets.flat()) expect(emitted.has(k), k).toBe(true)
  })
})
