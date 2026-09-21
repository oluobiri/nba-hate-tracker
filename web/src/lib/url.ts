// Cross-page state lives in the query string: ?lens=neg&tab=pos&n=250&all=1.
// Defaults come from the caller (the official threshold is a manifest
// value), so a link with only non-default state serialises short.
import { useCallback, useEffect, useRef, useState } from 'react'

import { LENSES, type Lens, type Sentiment } from './types'

export interface ViewState {
  lens: Lens
  tab: Sentiment
  n: number
  all: boolean
}

export interface ViewDefaults {
  threshold: number
}

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
  }
}

export function serializeViewState(s: ViewState, defaults: ViewDefaults): string {
  const q = new URLSearchParams()
  if (s.lens !== 'neg') q.set('lens', s.lens)
  if (s.tab !== 'neg') q.set('tab', s.tab)
  if (s.n !== defaults.threshold) q.set('n', String(s.n))
  if (s.all) q.set('all', '1')
  const str = q.toString()
  return str ? `?${str}` : ''
}

/** React hook: view state bound to the query string, with back/forward support. */
export function useViewState(
  defaults: ViewDefaults,
): [ViewState, (patch: Partial<ViewState>, opts?: { replace?: boolean }) => void] {
  const [state, setState] = useState(() => parseViewState(window.location.search, defaults))
  const latest = useRef(state)
  useEffect(() => {
    latest.current = state
  }, [state])
  useEffect(() => {
    const onPop = () => setState(parseViewState(window.location.search, defaults))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [defaults])
  const update = useCallback(
    (patch: Partial<ViewState>, opts?: { replace?: boolean }) => {
      // History writes stay outside the setState updater: StrictMode runs
      // updaters twice, which double-pushed entries and broke Back.
      const next = { ...latest.current, ...patch }
      latest.current = next
      const url = serializeViewState(next, defaults) || window.location.pathname
      if (opts?.replace) history.replaceState(null, '', url)
      else history.pushState(null, '', url)
      setState(next)
    },
    [defaults],
  )
  return [state, update]
}
