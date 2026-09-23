// One leaderboard row, the whole row a link. Rank numeral (hollow below
// the official minimum), grayscale mug, name and team, the bar, the lens
// value (the n column already is the value in the volume lens), n, and
// the rank-delta chip in a custom view.
import { motion } from 'motion/react'

import { fmtInt, fmtPct } from '../lib/format'
import { headshotSrcSet } from '../lib/media'
import { LENS_META } from '../lib/metrics'
import type { Counts, Lens } from '../lib/types'
import { RankNumeral } from './RankNumeral'
import { SentimentBar } from './SentimentBar'

export interface BoardRowProps {
  /** Null when the row is under the current threshold: unranked, ghosted. */
  rank: number | null
  /** At or above the official minimum: solid numeral. */
  official: boolean
  name: string
  slug: string
  abbr: string | null
  headshot: string
  counts: Counts
  lens: Lens
  /** Share of #1's total, for the volume lens's relative bar. */
  scale?: number
  /** Rank movement against the official view; null hides the chip. */
  delta?: number | null
}

const signed = (n: number): string => (n > 0 ? `+${n}` : String(n))

export function BoardRow({ rank, official, name, slug, abbr, headshot, counts, lens, scale = 1, delta = null }: BoardRowProps) {
  const meta = LENS_META[lens]
  const value = meta.value(counts)
  const ghost = rank === null
  return (
    <motion.li className={`row${ghost ? ' row--ghost' : ''}`} layout="position" transition={{ type: 'spring', stiffness: 380, damping: 36, mass: 0.8 }}>
      <a className="row__link" href={`/player/${slug}/`}>
        <span className="row__rank">{rank === null ? <span className="row__unranked mono">—</span> : <RankNumeral rank={rank} official={official} />}</span>
        <img className="row__mug" src={headshot} srcSet={headshotSrcSet(headshot)} sizes="40px" width="40" height="40" alt="" loading="lazy" decoding="async" />
        <span className="row__who">
          <span className="row__name">{name}</span>
          <span className="row__team mono">{abbr ?? 'Free agent'}</span>
          {!official && rank !== null && <span className="row__chip row__chip--unofficial mono">Unofficial</span>}
          {delta !== null && delta !== 0 && (
            <span className="row__chip mono" title="Rank change against the official view">
              {signed(delta)}
            </span>
          )}
        </span>
        <span className="row__bar">
          <SentimentBar counts={counts} size="row" length={meta.kind === 'count' ? 'relative' : 'full'} scale={scale} subject={name} />
        </span>
        {meta.kind === 'rate' && <span className={`row__value mono row__value--${lens}`}>{fmtPct(value)}</span>}
        <span className="row__n mono">{fmtInt(counts.total)}</span>
        <span className="row__chevron" aria-hidden="true">
          ›
        </span>
      </a>
    </motion.li>
  )
}
