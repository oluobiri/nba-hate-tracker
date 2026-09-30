// The feed at t, newest first: his comments, or the room's that kept a
// body. Density is a display choice (every comment, or the top-scored per
// minute). Not a live region: the score bug is the accessible summary.
import type { Density, FeedView, ReplayComment } from '../../lib/replay'
import { FeedCard } from './FeedCard'

export interface FeedProps {
  items: ReplayComment[]
  /** Whether more sit behind the slice. */
  more: boolean
  view: FeedView
  density: Density
  /** His name, for the his | room labels. */
  name: string
  /** A break in progress: its card sits at the top of the feed. */
  card: { label: string; n: number } | null
  stamp: (c: ReplayComment) => string
  wall: (c: ReplayComment) => string
  onView?: (view: FeedView) => void
  onDensity?: (density: Density) => void
  onMore?: () => void
}

export function Feed({ items, more, view, density, name, card, stamp, wall, onView, onDensity, onMore }: FeedProps) {
  return (
    <div className="fd">
      <div className="fd__controls">
        <div className="fd__views" role="group" aria-label="Whose comments">
          <button type="button" className="btn" aria-pressed={view === 'his'} onClick={() => onView?.('his')} disabled={!onView}>
            About {name}
          </button>
          <button type="button" className="btn" aria-pressed={view === 'room'} onClick={() => onView?.('room')} disabled={!onView}>
            The room
          </button>
        </div>
        <button
          type="button"
          className="btn btn--small fd__density"
          aria-pressed={density === 'minute'}
          onClick={() => onDensity?.(density === 'minute' ? 'all' : 'minute')}
          disabled={!onDensity}
        >
          Top per minute
        </button>
      </div>
      {card && (
        <p className="fd__card mono">
          {card.label} · {card.n.toLocaleString('en-US')} {card.n === 1 ? 'comment' : 'comments'} about him
        </p>
      )}
      {items.length === 0 ? (
        <p className="fd__empty">Nothing yet.</p>
      ) : (
        <ol className="fd__list">
          {items.map((c) => (
            <li key={c.id}>
              <FeedCard comment={c} stamp={stamp(c)} wall={wall(c)} />
            </li>
          ))}
        </ol>
      )}
      {more && (
        <div className="fd__foot">
          <button type="button" className="btn" onClick={onMore} disabled={!onMore}>
            Show more
          </button>
        </div>
      )}
    </div>
  )
}
