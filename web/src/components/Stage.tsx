import type { ReactNode } from 'react'

import { fmtInt } from '../lib/format'

export interface StageProps {
  /** 1-based; printed with a leading zero. */
  n: number
  name: string
  /** Where this step happens: a source, a file, a model. */
  where: string
  /** The season's count at this step, already formatted ("2,110,485 kept"). */
  count: string
  /** 0–1 of the downloaded total: draws the proportion bar. Absent for a step with no population. */
  share?: number
  /** What drops out here, as a line under the body: the count in bone, the sentence after it. */
  drop?: { count?: number; text: string }
  children: ReactNode
}

/** One step of the walkthrough: its number and name down the side with the count, the comment's state across. */
export function Stage({ n, name, where, count, share, drop, children }: StageProps) {
  return (
    <li className="stage">
      <div className="stage__id">
        <span className="stage__n" aria-hidden="true">
          {String(n).padStart(2, '0')}
        </span>
        <span className="stage__name">{name}</span>
        <span className="stage__where">{where}</span>
        <span className="stage__count">
          {count}
          {share !== undefined && (
            <span className="stage__bar" aria-hidden="true">
              <i style={{ width: `${(100 * share).toFixed(1)}%` }} />
            </span>
          )}
        </span>
      </div>
      <div className="stage__body">
        {children}
        {drop && (
          <p className="stage__drop">
            <span aria-hidden="true">↳</span> {drop.count !== undefined && <b>{fmtInt(drop.count)}</b>} {drop.text}
          </p>
        )}
      </div>
    </li>
  )
}

/** The comment as it stands at a step: verbatim, its sentiment as the edge once one is known. */
export function Said({ tone = 'neu', children }: { tone?: 'neg' | 'neu' | 'pos'; children: ReactNode }) {
  return <blockquote className={`said said--${tone}`}>{children}</blockquote>
}
