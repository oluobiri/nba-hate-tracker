// One row of the race, the whole row a link. Rank, name over team and the
// movement chip, then one solid bar in heat or ice sized against the week's
// leader, the face at its end and the figure with n just past it.
import { animate, motion, useMotionValue, useTransform } from 'motion/react'
import { type CSSProperties, type Ref, useEffect } from 'react'

import { fmtInt, fmtPct } from '../lib/format'
import { headshotSrcSet, headshotVariant } from '../lib/media'
import { type Move, moveLabel } from '../lib/race'
import type { RaceBy, RaceMode } from '../lib/url'
import { RankNumeral } from './RankNumeral'

export interface RaceRowProps {
  rank: number
  name: string
  slug: string
  abbr: string | null
  headshot: string
  mode: RaceMode
  by: RaceBy
  /** The share (a fraction) or the count the race ranks by. */
  value: number
  n: number
  /** The bar's length against the week's leader, 0 to 1. */
  share: number
  /** Movement against the previous week; null hides the chip. */
  move?: Move | null
  /** Seconds the bar takes to reach a new length; 0 steps. */
  travel?: number
  /** Seconds the figure counts to a new value; 0 steps. */
  count?: number
  /** Fade in and out as the row joins and leaves the board. */
  presence?: boolean
  ref?: Ref<HTMLLIElement>
}

const MOVE_TEXT = (m: Move): string => (m === 'new' ? 'new this week' : m > 0 ? `up ${m}` : `down ${-m}`)

// The figure, counting to each new value over `seconds`.
function Figure({ value, by, seconds }: { value: number; by: RaceBy; seconds: number }) {
  const shown = useMotionValue(value)
  const text = useTransform(shown, (v) => (by === 'rate' ? fmtPct(v) : fmtInt(Math.round(v))))
  useEffect(() => {
    if (seconds <= 0) {
      shown.set(value)
      return
    }
    const run = animate(shown, value, { duration: seconds, ease: 'linear' })
    return () => run.stop()
  }, [shown, value, seconds])
  return <motion.span>{text}</motion.span>
}

export function RaceRow({ rank, name, slug, abbr, headshot, mode, by, value, n, share, move = null, travel = 0, count = 0, presence = false, ref }: RaceRowProps) {
  const fade = presence ? { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0, transition: { duration: 0.2 } } } : {}
  return (
    <motion.li ref={ref} className="rrow" layout="position" transition={{ layout: { duration: 0.7, ease: [0.45, 0.05, 0.3, 1] }, opacity: { duration: 0.35 } }} {...fade}>
      <a className="rrow__link" href={`/player/${slug}/`}>
        <span className="rrow__rank">
          <RankNumeral rank={rank} official />
        </span>
        <span className="rrow__who">
          <span className="rrow__name">{name}</span>
          <span className="rrow__team mono">
            <span>{abbr ?? 'Free agent'}</span>
            {move !== null && (
              <span className="row__chip">
                <span aria-hidden="true">{moveLabel(move)}</span>
                <span className="visually-hidden">{MOVE_TEXT(move)}</span>
              </span>
            )}
          </span>
        </span>
        <span className="rrow__track">
          <motion.span
            className={`rrow__fill rrow__fill--${mode}`}
            style={{ '--v': share } as CSSProperties}
            initial={false}
            animate={{ '--v': share }}
            transition={{ duration: travel, ease: 'linear' }}
          >
            <img className="rrow__mug" src={headshotVariant(headshot, 180)} srcSet={headshotSrcSet(headshot)} sizes="38px" width="38" height="38" alt="" decoding="async" />
          </motion.span>
          <span className="rrow__lab">
            <span className={`rrow__val rrow__val--${mode} mono`}>
              {/* A toggle changes what the figure measures: a fresh figure, never a count across the two. */}
              <Figure key={`${mode}-${by}`} value={value} by={by} seconds={count} />
            </span>
            <span className="rrow__n mono">n={fmtInt(n)}</span>
          </span>
        </span>
      </a>
    </motion.li>
  )
}
