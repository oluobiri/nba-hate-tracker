// The caption under the court: what just happened, from the feed's own
// description. His plays take the bone edge; his moments take the whole
// line, with the label, the words, and a bar that drains while they hold.
import '../../styles/replay.css'
import type { CSSProperties } from 'react'

import type { Moment } from '../../lib/replay'

export interface CaptionProps {
  /** "Q3 4:12". */
  stamp: string
  text: string
  /** The play is his. */
  his: boolean
  /** The moment holding the caption; its index keys the bar's animation. */
  hot: Moment | null
  /** "WEMBANYAMA", shown with a moment. */
  who: string
  /** How long a moment holds, in seconds. */
  hold: number
}

export function Caption({ stamp, text, his, hot, who, hold }: CaptionProps) {
  if (hot) {
    return (
      <div className="caption caption--his caption--hot" data-testid="caption" key={hot.i}>
        <span className="caption__clock mono">{stamp}</span>
        <span className="caption__who mono">{who}</span>
        <span className="caption__label">{hot.label}</span>
        <span className="caption__text">{hot.text}</span>
        <span className="caption__hold" style={{ '--hold': `${hold}s` } as CSSProperties} aria-hidden="true">
          <i />
        </span>
      </div>
    )
  }
  return (
    <div className={`caption${his ? ' caption--his' : ''}`} data-testid="caption">
      <span className="caption__clock mono">{stamp}</span>
      <span className="caption__text">{text}</span>
    </div>
  )
}
