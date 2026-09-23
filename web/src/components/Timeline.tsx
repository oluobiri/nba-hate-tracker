// A player's season, week by week: two rolling lines over faint weekly
// dots sized by n, neutral phase bands, worst and best week marked, and
// every week a focusable column whose readout lists its games. SVG holds
// only the lines; every word is HTML, so text never scales with width.
import type { CSSProperties } from 'react'

import { fmtInt, fmtPct } from '../lib/format'
import { negRate, posRate } from '../lib/metrics'
import type { Counts } from '../lib/types'
import { type PhaseBand, weekLabel } from '../lib/weeks'

export interface TimelineWeek {
  /** The Monday key. */
  key: string
  counts: Counts | null
  /** That week's games, already worded ("W vs BOS 112–98"). */
  games: readonly string[]
}

export interface TimelineProps {
  name: string
  /** Spine-aligned. */
  weeks: readonly TimelineWeek[]
  negLine: readonly (number | null)[]
  posLine: readonly (number | null)[]
  bands: readonly PhaseBand[]
  marks: { worst: number | null; best: number | null }
  /** rules.floors.week_min_n */
  floor: number
  /** The rolling window, in weeks. */
  k: number
  /** The computed sentence: the chart's text alternative, shown above it. */
  summary: string
}

// Weeks a band needs before its label shows: on a desk, and on a phone.
const WIDE_BAND = 4
const WIDER_BAND = 8
// A month label needs this many weeks before the next one, or it goes.
const MONTH_GAP = 3
// Above this share of the chart's height a mark's label sits below its dot.
const HIGH = 0.8
// Past this share of the width a mark's label hangs left of its dot; on a phone, past MID.
const LATE = 0.6
const MID = 0.4
// Dot diameter range, px.
const DOT_MIN = 4
const DOT_MAX = 14

/** Path segments through the non-null points; a gap breaks the line. */
function linePath(values: readonly (number | null)[], n: number, ymax: number): string {
  let d = ''
  let pen = false
  values.forEach((v, i) => {
    if (v === null) {
      pen = false
      return
    }
    const x = ((i + 0.5) / n) * 100
    const y = 100 - (v / ymax) * 100
    d += `${pen ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)}`
    pen = true
  })
  return d
}

const lastIndex = (line: readonly (number | null)[]): number => line.reduce<number>((last, v, i) => (v === null ? last : i), -1)

const monthOf = (key: string): string => new Date(Date.parse(key.slice(0, 10))).toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' })

export function Timeline({ name, weeks, negLine, posLine, bands, marks, floor, k, summary }: TimelineProps) {
  const n = weeks.length
  const drawn = [...negLine, ...posLine].filter((v): v is number => v !== null)
  if (drawn.length < 2) {
    return (
      <figure className="tl tl--empty">
        <p className="tl__summary">{summary}</p>
      </figure>
    )
  }
  const rates = weeks.flatMap((w) => (w.counts && w.counts.total >= floor ? [negRate(w.counts), posRate(w.counts)] : []))
  const ymax = Math.min(1, Math.max(0.3, Math.ceil((Math.max(...drawn, ...rates) + 0.05) * 10) / 10))
  const maxN = Math.max(1, ...weeks.map((w) => w.counts?.total ?? 0))
  const xOf = (i: number): string => `${(((i + 0.5) / n) * 100).toFixed(2)}%`
  const yOf = (v: number): string => `${((v / ymax) * 100).toFixed(2)}%`
  const negEnd = lastIndex(negLine)
  const posEnd = lastIndex(posLine)
  // Two end labels too close read as one; the lower one drops a little.
  const negEndY = negEnd < 0 ? null : (negLine[negEnd]! / ymax) * 100
  const posEndY = posEnd < 0 ? null : (posLine[posEnd]! / ymax) * 100
  const collide = negEndY !== null && posEndY !== null && Math.abs(negEndY - posEndY) < 9
  const months = weeks
    .map((w, i) => ({ i, m: monthOf(w.key) }))
    .filter((x, i, arr) => i === 0 || x.m !== arr[i - 1]!.m)
    .filter((x, i, arr) => i === arr.length - 1 || arr[i + 1]!.i - x.i >= MONTH_GAP)

  const weekText = (w: TimelineWeek): string => {
    const head = `Week of ${weekLabel(w.key)}`
    const games = w.games.length ? ` Games: ${w.games.join('; ')}.` : ' No games.'
    if (!w.counts) return `${head}: no comments.${games}`
    if (w.counts.total < floor) return `${head}: ${fmtInt(w.counts.total)} comments, under the floor of ${fmtInt(floor)}.${games}`
    return `${head}: ${fmtPct(negRate(w.counts), 0)} negative, ${fmtPct(posRate(w.counts), 0)} positive of ${fmtInt(w.counts.total)} comments.${games}`
  }

  const mark = (i: number, kind: 'worst' | 'best') => {
    const c = weeks[i]!.counts!
    const rate = kind === 'worst' ? negRate(c) : posRate(c)
    const late = i / n > LATE
    const mid = i / n > MID
    const share = rate / ymax
    // The worst week's label sits above its dot, the best week's below, unless the edge is near.
    const below = kind === 'worst' ? share > HIGH : share > 1 - HIGH
    return (
      <span key={kind} className={`tl__mark tl__mark--${kind}${late ? ' tl__mark--late' : ''}${mid ? ' tl__mark--mid' : ''}${below ? ' tl__mark--below' : ''}`} style={{ left: xOf(i), bottom: yOf(rate) }}>
        <span className="tl__mark-text mono">
          {kind === 'worst' ? 'Worst week' : 'Best week'} · {fmtPct(rate, 0)} {kind === 'worst' ? 'negative' : 'positive'} · {weekLabel(weeks[i]!.key)}
        </span>
      </span>
    )
  }

  return (
    <figure className="tl" style={{ '--tl-n': n } as CSSProperties}>
      <p className="tl__summary">{summary}</p>
      <div className="tl__chart">
        <div className="tl__bands" aria-hidden="true">
          {bands.map((b) => (
            <span
              key={`${b.phase}-${b.start}`}
              className={`tl__band tl__band--${b.phase}${b.end - b.start >= WIDE_BAND ? ' tl__band--wide' : ''}${b.end - b.start >= WIDER_BAND ? ' tl__band--wider' : ''}`}
              style={{ left: `${(b.start / n) * 100}%`, width: `${((b.end - b.start) / n) * 100}%` }}
            >
              <span className="tl__band-label">{b.label}</span>
            </span>
          ))}
        </div>
        <div className="tl__dots" aria-hidden="true">
          {weeks.map((w, i) =>
            w.counts && w.counts.total >= floor ? (
              <span key={w.key}>
                <span className="tl__dot tl__dot--neg" style={{ left: xOf(i), bottom: yOf(negRate(w.counts)), '--tl-d': `${DOT_MIN + (DOT_MAX - DOT_MIN) * Math.sqrt(w.counts.total / maxN)}px` } as CSSProperties} />
                <span className="tl__dot tl__dot--pos" style={{ left: xOf(i), bottom: yOf(posRate(w.counts)), '--tl-d': `${DOT_MIN + (DOT_MAX - DOT_MIN) * Math.sqrt(w.counts.total / maxN)}px` } as CSSProperties} />
              </span>
            ) : null,
          )}
        </div>
        <svg className="tl__svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <path className="tl__line tl__line--pos" d={linePath(posLine, n, ymax)} vectorEffect="non-scaling-stroke" />
          <path className="tl__line tl__line--neg" d={linePath(negLine, n, ymax)} vectorEffect="non-scaling-stroke" />
        </svg>
        <div className="tl__marks" aria-hidden="true">
          {marks.worst !== null && mark(marks.worst, 'worst')}
          {marks.best !== null && mark(marks.best, 'best')}
        </div>
        <div className="tl__ends mono" aria-hidden="true">
          {negEndY !== null && (
            <span className="tl__end tl__end--neg" style={{ bottom: `${collide && negEndY < posEndY! ? negEndY - 5 : negEndY}%` }}>
              Negative {fmtPct(negLine[negEnd]!, 0)}
            </span>
          )}
          {posEndY !== null && (
            <span className="tl__end tl__end--pos" style={{ bottom: `${collide && posEndY <= negEndY! ? posEndY - 5 : posEndY}%` }}>
              Positive {fmtPct(posLine[posEnd]!, 0)}
            </span>
          )}
        </div>
        <ol className="tl__weeks" aria-label={`${name}, week by week`}>
          {weeks.map((w, i) => (
            <li
              key={w.key}
              className="tl__week"
              tabIndex={0}
              role="group"
              aria-label={weekText(w)}
              style={{ '--tl-i': i, left: `${(i / n) * 100}%` } as CSSProperties}
            >
              <span className="tl__tip" aria-hidden="true">
                <span className="tl__tip-head mono">
                  <b>{weekLabel(w.key)}</b>
                  {w.counts ? (
                    w.counts.total >= floor ? (
                      <>
                        {' '}
                        · <span className="tl__tip-neg">{fmtPct(negRate(w.counts), 0)} negative</span> · <span className="tl__tip-pos">{fmtPct(posRate(w.counts), 0)} positive</span> ·{' '}
                        {fmtInt(w.counts.total)} comments
                      </>
                    ) : (
                      <> · {fmtInt(w.counts.total)} comments, under the floor</>
                    )
                  ) : (
                    <> · no comments</>
                  )}
                </span>
                {w.games.length > 0 ? (
                  <ul className="tl__tip-games mono">
                    {w.games.map((g) => (
                      <li key={g}>{g}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="tl__tip-none">No games</span>
                )}
              </span>
            </li>
          ))}
        </ol>
      </div>
      <div className="tl__axis mono" aria-hidden="true">
        {months.map(({ i, m }) => (
          <span key={`${m}${i}`} className="tl__month" style={{ left: `${(i / n) * 100}%` }}>
            {m}
          </span>
        ))}
      </div>
      <div className="tl__readout" aria-hidden="true">
        <span className="tl__readout-hint mono">Hover or tap a week for its games.</span>
      </div>
      <figcaption className="visually-hidden">
        {k}-week rolling rates from summed counts; weeks under {fmtInt(floor)} comments are left off the lines.
      </figcaption>
    </figure>
  )
}
