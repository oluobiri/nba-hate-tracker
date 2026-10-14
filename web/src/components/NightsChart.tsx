// The season night by night: two pooled lines over nightly dots sized by
// n, the regular-season levels as dashed rules, neutral phase bands, the
// draft marked, the stretch above the level bracketed, two annotations on
// their rings. Every night is a focusable column whose readout lands under
// the axis. SVG holds only the lines; every word is HTML.
import type { CSSProperties } from 'react'

import { fmtInt, fmtPct } from '../lib/format'
import { negRate, neuRate, posRate } from '../lib/metrics'
import { addDays, againstLevel, dayLabel, type Night, type NightNote, NIGHT_PHASE_LABELS, nightText, nightWhat, type SeasonCalendar, type Stretch } from '../lib/season'

export interface NightsChartProps {
  nights: readonly Night[]
  negLine: readonly (number | null)[]
  posLine: readonly (number | null)[]
  /** The regular season's shares. */
  level: { neg: number; pos: number }
  stretch: Stretch | null
  notes: readonly NightNote[]
  cal: SeasonCalendar
  /** The pooled window, in nights. */
  k: number
  /** Nights under this many comments are drawn but never set the axis. */
  floor: number
}

// Dot diameter range, px.
const DOT_MIN = 3
const DOT_MAX = 12
// Band widths, in % of the chart, that earn a label: always, on a desk, on a wide desk.
const BAND_ALWAYS = 15
const BAND_DESK = 7
const BAND_WIDE = 3.5
// A month label this close to the right edge goes.
const MONTH_EDGE = 96

const DAY_MS = 86_400_000

const bandClass = (w: number): string => (w >= BAND_ALWAYS ? ' ch__band--always' : w >= BAND_DESK ? ' ch__band--desk' : w >= BAND_WIDE ? ' ch__band--wide' : '')
const firstOfNextMonth = (t: number): number => new Date(t).setUTCMonth(new Date(t).getUTCMonth() + 1, 1)

type Band = { key: string; label: string; from: string; to: string }

/** The phases clipped to the nights on the chart: a season in progress ends mid-band. */
function phaseBands(nights: readonly Night[], cal: SeasonCalendar): Band[] {
  const first = nights[0]!.day
  const end = addDays(nights.at(-1)!.day, 1)
  const clip = (d: string): string => (d < first ? first : d > end ? end : d)
  return [
    { key: 'pre', label: NIGHT_PHASE_LABELS.pre, from: first, to: cal.opening_night },
    { key: 'regular', label: NIGHT_PHASE_LABELS.regular, from: cal.opening_night, to: cal.play_in_start },
    { key: 'play_in', label: 'Play-in', from: cal.play_in_start, to: cal.playoffs_start },
    { key: 'playoffs', label: NIGHT_PHASE_LABELS.playoffs, from: cal.playoffs_start, to: cal.finals_start },
    { key: 'finals', label: 'Finals', from: cal.finals_start, to: addDays(cal.finals_end, 1) },
    { key: 'off', label: NIGHT_PHASE_LABELS.off, from: addDays(cal.finals_end, 1), to: end },
  ]
    .map((b) => ({ ...b, from: clip(b.from), to: clip(b.to) }))
    .filter((b) => b.to > b.from)
}

/** Path segments through the non-null points; a gap breaks the line. */
function linePath(values: readonly (number | null)[], n: number, y: (v: number) => number): string {
  let d = ''
  let pen = false
  values.forEach((v, i) => {
    if (v === null) {
      pen = false
      return
    }
    d += `${pen ? 'L' : 'M'}${(((i + 0.5) / n) * 100).toFixed(2)} ${(100 - y(v)).toFixed(2)}`
    pen = true
  })
  return d
}

export function NightsChart({ nights, negLine, posLine, level, stretch, notes, cal, k, floor }: NightsChartProps) {
  const n = nights.length
  const t0 = Date.parse(nights[0]!.day)
  const idx = (iso: string): number => Math.round((Date.parse(iso) - t0) / DAY_MS)
  const xDay = (iso: string): number => ((idx(iso) + 0.5) / n) * 100
  const xEdge = (iso: string): number => (idx(iso) / n) * 100
  const xAt = (i: number): number => ((i + 0.5) / n) * 100

  // The axis: the lines and the dots at the floor, rounded out to five points.
  const drawn = [...negLine, ...posLine].filter((v): v is number => v !== null)
  const big = nights.filter((x) => x.counts.total >= floor).flatMap((x) => [negRate(x.counts), posRate(x.counts)])
  const values = [...drawn, ...big, level.neg, level.pos]
  const lo = Math.max(0, Math.floor((Math.min(...values) - 0.01) * 20) / 20)
  const hi = Math.min(1, Math.ceil((Math.max(...values) + 0.01) * 20) / 20)
  const y = (v: number): number => ((v - lo) / (hi - lo)) * 100
  const ticks: number[] = []
  for (let t = Math.ceil(lo * 10) / 10; t <= hi + 1e-9; t += 0.1) ticks.push(Math.round(t * 10) / 10)
  const maxN = Math.max(1, ...nights.map((x) => x.counts.total))
  const dot = (x: Night): string => `${(DOT_MIN + (DOT_MAX - DOT_MIN) * Math.sqrt(x.counts.total / maxN)).toFixed(1)}px`

  // The area between the negative line and the level, where the line is above it.
  const area = [
    ...nights.map((_, i) => [xAt(i), y(negLine[i] === null ? level.neg : Math.max(negLine[i]!, level.neg))] as const),
    [xAt(n - 1), y(level.neg)] as const,
    [xAt(0), y(level.neg)] as const,
  ]
  const clip = `polygon(${area.map(([px, py]) => `${px.toFixed(2)}% ${(100 - py).toFixed(2)}%`).join(',')})`

  const bands = phaseBands(nights, cal).map((b) => ({ ...b, left: xEdge(b.from), width: xEdge(b.to) - xEdge(b.from) }))
  // A label on the first of each month after the first night.
  const months: { x: number; label: string }[] = []
  const end = Date.parse(addDays(nights.at(-1)!.day, 1))
  for (let t = firstOfNextMonth(new Date(t0).setUTCHours(0, 0, 0, 0)); t < end; t = firstOfNextMonth(t)) {
    const x = ((t - t0) / DAY_MS / n) * 100
    if (x < MONTH_EDGE) months.push({ x, label: new Date(t).toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' }) })
  }
  // The bracket closes where the line came back, or after the counted nights.
  const bracketRight = stretch ? xEdge(stretch.to ?? addDays(stretch.from, stretch.nights)) : 0

  return (
    <figure className="nc fig">
      <div className="fig__head">
        <ul className="key">
          <li>
            <i className="key__line key__line--neg" /> Negative share
          </li>
          <li>
            <i className="key__line key__line--pos" /> Positive share
          </li>
          <li>
            <i className="key__dot" /> Each night, sized by its comments
          </li>
          <li>
            <i className="key__line key__line--rule" /> Regular-season level
          </li>
        </ul>
        <span className="fig__quiet mono">Lines: the {fmtInt(k)} nights around each night</span>
      </div>
      <div className="ch nc__chart">
        <div className="ch__bands" aria-hidden="true">
          {bands.map((b) => (
            <span key={b.key} className={`ch__band ch__band--${b.key}${bandClass(b.width)}`} style={{ left: `${b.left}%`, width: `${b.width}%` }}>
              <span className="ch__band-label">{b.label}</span>
            </span>
          ))}
        </div>
        <div className="ch__grid" aria-hidden="true">
          {ticks.map((t, i) => (
            <span key={t} className="ch__tick-row" style={{ bottom: `${y(t)}%` }}>
              <span className="ch__tick-label">
                {fmtPct(t, 0)}
                {i === ticks.length - 1 && <em> of the night</em>}
              </span>
            </span>
          ))}
        </div>
        <div className="ch__layer" aria-hidden="true">
          <span className="ch__fill ch__fill--harsh" style={{ clipPath: clip }} />
          <span className="ch__rule" style={{ bottom: `${y(level.neg)}%` }} />
          <span className="ch__rule ch__rule--pos" style={{ bottom: `${y(level.pos)}%` }} />
          {cal.draft >= nights[0]!.day && cal.draft <= nights.at(-1)!.day && (
            <span className="ch__mark" style={{ left: `${xDay(cal.draft)}%`, height: `${y(ticks.at(-1)!)}%` }}>
              <span>Draft</span>
            </span>
          )}
          {nights.map((x, i) =>
            x.counts.total ? (
              <span key={x.day}>
                <span className="ch__dot ch__dot--pos" style={{ left: `${xAt(i)}%`, bottom: `${y(posRate(x.counts))}%`, '--d': dot(x) } as CSSProperties} />
                <span className="ch__dot ch__dot--neg" style={{ left: `${xAt(i)}%`, bottom: `${y(negRate(x.counts))}%`, '--d': dot(x) } as CSSProperties} />
              </span>
            ) : null,
          )}
        </div>
        <svg className="ch__svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <path className="ch__line ch__line--pos" d={linePath(posLine, n, y)} vectorEffect="non-scaling-stroke" />
          <path className="ch__line ch__line--neg" d={linePath(negLine, n, y)} vectorEffect="non-scaling-stroke" />
        </svg>
        <div className="ch__layer" aria-hidden="true">
          <span className="ch__rule-label mono" style={{ bottom: `${y(level.neg)}%` }}>
            <em>Regular season </em>
            {fmtPct(level.neg, 1)}
          </span>
          <span className="ch__rule-label ch__rule-label--pos mono" style={{ bottom: `${y(level.pos)}%` }}>
            <em>Regular season </em>
            {fmtPct(level.pos, 1)}
          </span>
          {stretch && (
            <>
              <span className="ch__brace" style={{ left: `${xEdge(stretch.from)}%`, width: `${bracketRight - xEdge(stretch.from)}%` }} />
              <span className="ch__brace-label mono" style={{ left: `clamp(80px, ${(xEdge(stretch.from) + bracketRight) / 2}%, calc(100% - 80px))` }}>
                <span className="wide-only">
                  {fmtInt(stretch.nights)} nights above the regular season
                </span>
                <span className="narrow-only">{fmtInt(stretch.nights)} nights above</span>
              </span>
            </>
          )}
          {notes.map((note) => (
            <span key={note.day}>
              <span className={`ch__ring ch__ring--${note.pole}`} style={{ left: `${xDay(note.day)}%`, bottom: `${y(note.rate)}%` }} />
              {note.also && <span className={`ch__ring ch__ring--${note.pole} ch__ring--small`} style={{ left: `${xDay(note.also.day)}%`, bottom: `${y(note.also.rate)}%` }} />}
              <p
                className={`ch__note ch__note--${note.pole}`}
                style={note.pole === 'neg' ? { right: `calc(${100 - xDay(note.day)}% + 12px)`, top: '4px' } : { right: `calc(${100 - xDay(note.day)}% + 12px)`, bottom: `${Math.max(2, y(note.rate) - 30)}%` }}
              >
                <b>
                  <span className="wide-only">{note.head}</span>
                  <span className="narrow-only">{note.shortHead}</span>
                </b>
                <span className="wide-only">{note.text}</span>
                <span className="narrow-only">{note.shortText}</span>
              </p>
            </span>
          ))}
        </div>
        <ol className="ch__cols" aria-label="The season, night by night" style={{ '--n': n } as CSSProperties}>
          {nights.map((x, i) => {
            const neg = negLine[i]!
            const pos = posLine[i]!
            return (
              <li key={x.day} className="ch__col" tabIndex={0} role="group" aria-label={nightText(x, cal, neg, pos, level.neg, k)} style={{ '--i': i, left: `${(i / n) * 100}%` } as CSSProperties}>
                {x.counts.total > 0 && (
                  <>
                    <span className="ch__pt ch__pt--neg" style={{ bottom: `${y(negRate(x.counts))}%` }} />
                    <span className="ch__pt ch__pt--pos" style={{ bottom: `${y(posRate(x.counts))}%` }} />
                  </>
                )}
                <span className="ch__tip ro" aria-hidden="true">
                  <span className="ro__head">
                    <b>{dayLabel(x.day)}</b>
                    <span className="mono">{nightWhat(x, cal)}</span>
                    <span className="mono">{fmtInt(x.counts.total)} comments</span>
                  </span>
                  {x.counts.total > 0 ? (
                    <>
                      <span className="ro__quiet mono">That night</span>
                      <span className="ro__bar mono">
                        <b className="ro__bar-neg" style={{ width: `${negRate(x.counts) * 100}%` }}>
                          {fmtPct(negRate(x.counts), 1)}
                        </b>
                        <b className="ro__bar-neu" style={{ width: `${neuRate(x.counts) * 100}%` }}>
                          {fmtPct(neuRate(x.counts), 1)}
                        </b>
                        <b className="ro__bar-pos" style={{ width: `${posRate(x.counts) * 100}%` }}>
                          {fmtPct(posRate(x.counts), 1)}
                        </b>
                      </span>
                      <span className="ro__line">
                        {neg === null || pos === null ? (
                          'Too close to the edge of the season for the line.'
                        ) : (
                          <>
                            <span className="ro__quiet mono">The line</span> · the {fmtInt(k)} nights around it, all comments added up: <b className="neg">{fmtPct(neg, 1)}</b> negative and <b className="pos">{fmtPct(pos, 1)}</b> positive. {againstLevel(neg, level.neg)}
                          </>
                        )}
                      </span>
                    </>
                  ) : (
                    <span className="ro__hint">No comments.</span>
                  )}
                </span>
              </li>
            )
          })}
        </ol>
      </div>
      <ol className="months" aria-hidden="true">
        {months.map((m) => (
          <li key={m.label + m.x} style={{ left: `${m.x}%` }}>
            {m.label}
          </li>
        ))}
      </ol>
      <div className="ro ro--reserve" aria-hidden="true">
        <p className="ro__hint">Hover or tap anywhere on the chart to read one night: its comments, its split, and the {fmtInt(k)}-night line through it.</p>
      </div>
      <figcaption className="visually-hidden">
        Each point on a line is the {fmtInt(k)} nights around it with their comments added up, then the share taken; the dashed rules are the regular season's shares.
      </figcaption>
    </figure>
  )
}
