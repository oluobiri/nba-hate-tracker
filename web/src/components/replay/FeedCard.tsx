// One comment in the feed, in the Exhibit's clothes: the stamp where the
// exhibit prints its number, the flair, the body verbatim, the score, the
// wall clock, the source. Never a username.
import { fmtInt } from '../../lib/format'
import type { ReplayComment } from '../../lib/replay'
import type { Sentiment } from '../../lib/types'
import { commentUrl } from '../Exhibit'

export interface FeedCardProps {
  comment: ReplayComment
  /** "Q3 04:12", "Halftime". */
  stamp: string
  /** "9:47 PM ET". */
  wall: string
}

const SENTIMENT: Record<Sentiment, string> = { neg: 'Negative', neu: 'Neutral', pos: 'Positive' }

export function FeedCard({ comment: c, stamp, wall }: FeedCardProps) {
  return (
    <article className={`exhibit exhibit--${c.sentiment} fc`}>
      <header className="exhibit__head">
        <span>{stamp}</span>
        <span className="visually-hidden">{SENTIMENT[c.sentiment]}.</span>
        <span className="exhibit__flair">{c.flair ? `${c.flair} flair` : 'no flair'}</span>
      </header>
      <blockquote className="exhibit__body">{c.body ?? ''}</blockquote>
      <footer className="exhibit__foot">
        <span className="exhibit__meta mono">
          <span className="exhibit__score" aria-label={`${fmtInt(c.score)} points`}>
            ▲ {fmtInt(c.score)}
          </span>
          <span className="exhibit__date">{wall}</span>
          <a href={commentUrl(c.postId, c.id)} rel="noopener noreferrer">
            Source ↗
          </a>
        </span>
      </footer>
    </article>
  )
}
