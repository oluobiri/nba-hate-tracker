// Two bars, not a gauge: the room on him right now, over his last few
// comments (a count window, since density varies twentyfold across a game),
// and so far, cumulative. Negative → neutral → positive; no net sentiment.
import { fmtInt, fmtPct } from '../../lib/format'
import { negRate } from '../../lib/metrics'
import type { Counts } from '../../lib/types'
import { SentimentBar } from '../SentimentBar'

export interface RoomBarsProps {
  now: Counts
  soFar: Counts
  /** How many of his comments "right now" reads: RIGHT_NOW, by name. */
  window: number
  /** His season counts, for the so-far line's comparison. */
  usual: Counts
  subject: string
}

export function RoomBars({ now, soFar, window, usual, subject }: RoomBarsProps) {
  const nowDetail = now.total === 0 ? 'no comments yet' : now.total < window ? `his first ${fmtInt(now.total)} comments` : `his last ${fmtInt(window)} comments`
  return (
    <div className="rb">
      <div className="rb__bar">
        <p className="rb__label mono">
          Right now <span className="rb__detail">{nowDetail}</span>
        </p>
        {now.total > 0 ? <SentimentBar counts={now} size="row" subject={`${subject} right now`} /> : <div className="rb__empty" aria-hidden="true" />}
      </div>
      <div className="rb__bar">
        <p className="rb__label mono">
          So far{' '}
          <span className="rb__detail">
            {soFar.total === 0 ? 'no comments yet' : `${fmtInt(soFar.total)} comments`} · his usual {fmtPct(negRate(usual), 0)} negative
          </span>
        </p>
        {soFar.total > 0 ? <SentimentBar counts={soFar} size="row" subject={`${subject} so far`} /> : <div className="rb__empty" aria-hidden="true" />}
      </div>
    </div>
  )
}
