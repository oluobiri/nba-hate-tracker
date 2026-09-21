import { fmtInt } from '../lib/format'
import type { Sentiment } from '../lib/types'
import { Stamp, type StampKind } from './Stamp'

export interface ExhibitProps {
  number: number
  body: string
  sentiment: Sentiment
  score: number
  /** Reddit permalink to the comment. */
  sourceUrl: string
  /** The post the comment lived in; null when the bridge has no row for it. */
  postTitle: string | null
  stamp?: StampKind
}

const SENTIMENT: Record<Sentiment, string> = { neg: 'Negative', neu: 'Neutral', pos: 'Positive' }

/** A numbered receipt: the comment verbatim, its context, its source. Never a username. */
export function Exhibit({ number, body, sentiment, score, sourceUrl, postTitle, stamp }: ExhibitProps) {
  return (
    <article className="exhibit">
      <header className="exhibit__head">
        <span>Exhibit {String(number).padStart(2, '0')}</span>
        {stamp && <Stamp kind={stamp} />}
        <span className={`exhibit__sent exhibit__sent--${sentiment}`}>{SENTIMENT[sentiment]}</span>
      </header>
      <blockquote className="exhibit__body">{body}</blockquote>
      <footer className="exhibit__foot">
        {postTitle === null ? (
          <span className="exhibit__post exhibit__post--missing">Post unavailable</span>
        ) : (
          <span className="exhibit__post">{postTitle}</span>
        )}
        <span className="exhibit__score" aria-label={`${fmtInt(score)} points`}>
          ▲ {fmtInt(score)}
        </span>
        <a href={sourceUrl} rel="noopener noreferrer">
          Source
        </a>
      </footer>
    </article>
  )
}

/** The permalink of a comment from the fact's ids. */
export function commentUrl(linkId: string, commentId: string): string {
  return `https://www.reddit.com/r/nba/comments/${linkId.replace(/^t3_/, '')}/_/${commentId}/`
}
