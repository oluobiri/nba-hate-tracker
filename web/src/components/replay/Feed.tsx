// The room: the comments as they landed, newest first. About him or
// everyone; the top-voted one per beat of playback or every one. Flair and
// score, never a username; not a live region, the gauge is the accessible
// reading.
import '../../styles/replay.css'
import { idxAt } from '../../lib/clock'
import { fmtInt } from '../../lib/format'
import { type FeedDensity, type FeedSelection, type FeedView, lastName, type ReplayComment, type Room } from '../../lib/replay'
import { commentUrl } from '../Exhibit'

export interface FeedCardProps {
  comment: ReplayComment
  /** "on him", "on Fox"; null in the About-him view. */
  about: string | null
  /** The commenter's flair as a team abbreviation; null when unflaired. */
  flair: string | null
  /** Landed within the last beat: slides in. */
  fresh: boolean
}

const PHASE_TAGS: Record<string, string> = { pre: 'pre-game', break: 'break', post: 'post-game' }

export function FeedCard({ comment, about, flair, fresh }: FeedCardProps) {
  const phase = PHASE_TAGS[comment.phase]
  return (
    <li className={`fc fc--${comment.sentiment}${fresh ? ' fc--new' : ''}`}>
      <div className="fc__meta mono">
        {about && <span className="fc__about">{about}</span>}
        <span>{flair ? `${flair} flair` : 'no flair'}</span>
        {phase && <span>{phase}</span>}
        <span className="fc__score" aria-label={`${fmtInt(comment.score)} points`}>
          ▲ {fmtInt(comment.score)}
        </span>
        <a className="fc__source" href={commentUrl(comment.postId, comment.id)} rel="noopener noreferrer">
          Source ↗
        </a>
      </div>
      <p className="fc__body">{comment.body}</p>
    </li>
  )
}

export interface FeedProps {
  room: Room
  selection: FeedSelection
  u: number
  view: FeedView
  density: FeedDensity
  onView: (v: FeedView) => void
  onDensity: (d: FeedDensity) => void
  focusId: number
  /** player_id → attributed_player, for the "on …" tag. */
  names: ReadonlyMap<number, string>
  /** Team name → abbreviation, for the flair chip. */
  abbrOf: ReadonlyMap<string, string>
  /** "Tip-off at 8:43 PM ET.", for the empty state. */
  tipLine: string
}

/** Rows kept in the list; the phone shows fewer by CSS. */
const KEEP = 32
/** A comment that landed within this many replay seconds slides in. */
const FRESH = 1

export function Feed({ room, selection, u, view, density, onView, onDensity, focusId, names, abbrOf, tipLine }: FeedProps) {
  const k = idxAt(selection.u, u)
  const rows: ReplayComment[] = []
  for (let x = k; x >= Math.max(0, k - KEEP + 1); x--) rows.push(room.comments[selection.idx[x]!]!)
  const about = (c: ReplayComment): string | null => {
    if (view !== 'all' || c.playerId === null) return null
    if (c.playerId === focusId) return 'on him'
    const name = names.get(c.playerId)
    return name ? `on ${lastName(name)}` : null
  }
  return (
    <aside className="room replay__panel" aria-label="The room">
      <div className="replay__ph">
        <b>The room</b>
        <span>{density === 'top' ? 'top-voted, one at a time' : 'every comment'}</span>
      </div>
      <div className="room__toggles">
        <div className="room__seg" role="group" aria-label="Whose comments">
          <button type="button" className="btn room__btn" aria-pressed={view === 'him'} onClick={() => onView('him')}>
            About him
          </button>
          <button type="button" className="btn room__btn" aria-pressed={view === 'all'} onClick={() => onView('all')}>
            Everyone
          </button>
        </div>
        <div className="room__seg" role="group" aria-label="How many">
          <button type="button" className="btn room__btn" aria-pressed={density === 'top'} onClick={() => onDensity('top')}>
            Top
          </button>
          <button type="button" className="btn room__btn" aria-pressed={density === 'all'} onClick={() => onDensity('all')}>
            All
          </button>
        </div>
      </div>
      <ol className="feed" data-testid="feed">
        {rows.length === 0 ? (
          <li className="feed__empty mono">The thread is warming up. {tipLine}</li>
        ) : (
          rows.map((c) => <FeedCard key={c.id} comment={c} about={about(c)} flair={c.fanTeam ? (abbrOf.get(c.fanTeam) ?? null) : null} fresh={u - c.u < FRESH} />)
        )}
      </ol>
      <div className="room__fade" aria-hidden="true" />
    </aside>
  )
}
