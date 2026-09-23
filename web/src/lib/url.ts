// Cross-page state lives in the query string:
//   ?lens=neg&tab=pos&n=250&all=1&games=all&log=all
// Defaults come from the caller (the official threshold is a manifest
// value), so a link with only non-default state serialises short. `all`
// expands a page's primary list: the rows on the leaderboard, the receipts
// on a player page. The game log has its own keys so the two never collide.
import { useCallback, useMemo, useSyncExternalStore } from 'react'

import { LENSES, type Lens, type Sentiment } from './types'

// Games the room talked about (at or above the game floor) vs every game dressed.
export type GamesFilter = 'talked' | 'all'
// The first rows of the log vs the whole log.
export type LogRows = 'top' | 'all'

export interface ViewState {
  lens: Lens
  tab: Sentiment
  n: number
  all: boolean
  games: GamesFilter
  log: LogRows
}

export interface ViewDefaults {
  threshold: number
}

// The keys each island reads, so a page can hide a region's prerendered
// default until that island has taken over a deep link.
export const RECEIPT_KEYS: readonly string[] = ['tab', 'all']
export const GAME_KEYS: readonly string[] = ['games', 'log']

export function parseViewState(search: string, defaults: ViewDefaults): ViewState {
  const q = new URLSearchParams(search)
  const lens = q.get('lens')
  const tab = q.get('tab')
  const n = Number(q.get('n'))
  return {
    lens: LENSES.includes(lens as Lens) ? (lens as Lens) : 'neg',
    tab: tab === 'pos' || tab === 'neu' ? tab : 'neg',
    n: Number.isFinite(n) && n >= 1 ? Math.round(n) : defaults.threshold,
    all: q.get('all') === '1',
    games: q.get('games') === 'all' ? 'all' : 'talked',
    log: q.get('log') === 'all' ? 'all' : 'top',
  }
}

export function serializeViewState(s: ViewState, defaults: ViewDefaults): string {
  const q = new URLSearchParams()
  if (s.lens !== 'neg') q.set('lens', s.lens)
  if (s.tab !== 'neg') q.set('tab', s.tab)
  if (s.n !== defaults.threshold) q.set('n', String(s.n))
  if (s.all) q.set('all', '1')
  if (s.games !== 'talked') q.set('games', s.games)
  if (s.log !== 'top') q.set('log', s.log)
  const str = q.toString()
  return str ? `?${str}` : ''
}

// The query string is the store. pushState fires no event, so `update`
// notifies subscribers itself; popstate covers Back and Forward.
const listeners = new Set<() => void>()
function subscribe(cb: () => void): () => void {
  listeners.add(cb)
  window.addEventListener('popstate', cb)
  return () => {
    listeners.delete(cb)
    window.removeEventListener('popstate', cb)
  }
}
const getSnapshot = (): string => window.location.search
// Hydration renders the default view on both sides; React then re-renders
// once with the real query string, before which `ready` reads false.
const getServerSnapshot = (): string => ''

/**
 * React hook: view state bound to the query string, with back/forward support.
 * `ready` is false only for the hydration render of a deep link, when the
 * page still shows the default view. Pass a memoised `defaults`.
 */
export function useViewState(
  defaults: ViewDefaults,
): [ViewState, (patch: Partial<ViewState>, opts?: { replace?: boolean }) => void, boolean] {
  const search = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
  const state = useMemo(() => parseViewState(search, defaults), [search, defaults])
  const ready = typeof window !== 'undefined' && search === window.location.search
  const update = useCallback(
    (patch: Partial<ViewState>, opts?: { replace?: boolean }) => {
      const next = { ...parseViewState(window.location.search, defaults), ...patch }
      // The hash stays: a control inside #receipts must not lose the anchor.
      const url = (serializeViewState(next, defaults) || window.location.pathname) + window.location.hash
      if (opts?.replace) history.replaceState(null, '', url)
      else history.pushState(null, '', url)
      for (const cb of listeners) cb()
    },
    [defaults],
  )
  return [state, update, ready]
}
