// The game log: one island. Which games (the room talked about, or every
// game dressed) and how many rows, both in the URL. The verdict column is
// computed at build and arrives in the rows.
import { useLayoutEffect, useMemo } from 'react'

import '../styles/games.css'
import { fmtInt } from '../lib/format'
import type { GameLine } from '../lib/games'
import { useViewState } from '../lib/url'
import { GamesTable } from './GamesTable'

export interface GamesProps {
  name: string
  /** Newest first. */
  log: GameLine[]
  /** rules.floors.game_min_n */
  floor: number
  /** Rows before "Show all": a page choice. */
  top: number
  /** rules.qualified_threshold, the view state's one default. */
  official: number
}

export function Games({ name, log, floor, top, official }: GamesProps) {
  const defaults = useMemo(() => ({ threshold: official }), [official])
  const [view, update, ready] = useViewState(defaults)
  const { games, log: rows } = view

  useLayoutEffect(() => {
    if (ready) document.documentElement.classList.remove('has-games-view')
  }, [ready])

  const talked = useMemo(() => log.filter((g) => g.talked), [log])
  const filtered = games === 'all' ? log : talked
  const shown = rows === 'all' ? filtered : filtered.slice(0, top)
  const caption = games === 'all' ? `Every game ${name} dressed for, newest first.` : `Games the room talked about ${name} in, at least ${fmtInt(floor)} comments each, newest first.`

  return (
    <div className="gl">
      <div className="gl__toggle" role="group" aria-label="Which games">
        <button type="button" className="btn" aria-pressed={games === 'talked'} onClick={() => update({ games: 'talked' })}>
          Games the room talked about ({fmtInt(talked.length)})
        </button>
        <button type="button" className="btn" aria-pressed={games === 'all'} onClick={() => update({ games: 'all' })}>
          All games ({fmtInt(log.length)})
        </button>
      </div>
      {filtered.length === 0 ? (
        <p className="gl__empty">The room never reached {fmtInt(floor)} comments about {name} in one of his games.</p>
      ) : (
        <GamesTable rows={shown} caption={caption} />
      )}
      {filtered.length > top && (
        <div className="gl__foot">
          <button type="button" className="btn" onClick={() => update({ log: rows === 'all' ? 'top' : 'all' })}>
            {rows === 'all' ? `Show ${top}` : `Show all ${fmtInt(filtered.length)}`}
          </button>
        </div>
      )}
    </div>
  )
}
