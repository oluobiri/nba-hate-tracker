// The Belt and the Flowers: one track per title on a shared week axis. A
// cell's colour intensity follows the rate, so a weak win looks weak.
// Rendered twice by the page with a metric prop; the axis is rendered once.
import type { CSSProperties } from 'react'

import { fmtInt, fmtPct } from '../lib/format'
import { headshotSrcSet } from '../lib/media'
import { reignRate, reigns, tally, type Holder, type TitleMetric, type WeekRow } from '../lib/titles'

export interface TitleRow extends WeekRow {
  name: string
  slug: string
  headshot: string
}

export interface WeeklyTitlesProps {
  metric: TitleMetric
  /** The shared axis, ascending; every track spans all of it. */
  weeks: readonly string[]
  holders: readonly Holder<TitleRow>[]
  /** Merge consecutive weeks by one holder into a reign block. */
  merge?: boolean
  label: string
}

const day = (week: string): string =>
  new Date(`${week.slice(0, 10)}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })

/** The week labels, one per column. */
export function WeekAxis({ weeks }: { weeks: readonly string[] }) {
  return (
    <ol className="wk__axis mono" style={{ '--wk-n': weeks.length } as CSSProperties} aria-hidden="true">
      {weeks.map((w) => (
        <li key={w}>{day(w)}</li>
      ))}
    </ol>
  )
}

export function WeeklyTitles({ metric, weeks, holders, merge = false, label }: WeeklyTitlesProps) {
  const col = new Map(weeks.map((w, i) => [w, i + 1]))
  const blocks = merge ? reigns(holders, (r) => r.slug) : holders.map((h) => ({ from: h.week, to: h.week, weeks: 1, holders: [h] }))
  const held = new Set(blocks.flatMap((b) => b.holders.map((h) => h.week)))
  return (
    <ul className={`wk wk--${metric}`} style={{ '--wk-n': weeks.length } as CSSProperties} aria-label={`${label}, week by week`}>
      {blocks.map((b) => {
        const first = b.holders[0]!
        const rate = reignRate(b, metric)
        const n = b.holders.reduce((a, h) => a + h.row.total, 0)
        const start = col.get(b.from) ?? 1
        return (
          <li
            key={b.from}
            className={`wk__cell${b.weeks > 1 ? ' wk__cell--reign' : ''}`}
            style={{ gridColumn: `${start} / span ${b.weeks}`, '--wk-mix': `${Math.round(rate * 100)}%` } as CSSProperties}
          >
            <a className="wk__link" href={`/player/${first.row.slug}/`}>
              <span className="wk__week mono">
                {day(b.from)}
                {b.weeks > 1 && ` → ${day(b.to)} · ${b.weeks} wks`}
              </span>
              <img className="wk__mug" src={first.row.headshot} srcSet={headshotSrcSet(first.row.headshot)} sizes="100px" width="100" height="72" alt="" loading="lazy" decoding="async" />
              <span className="wk__name">{first.row.name}</span>
              <span className="wk__rate mono">{fmtPct(rate)}</span>
              <span className="wk__n mono">n={fmtInt(n)}</span>
            </a>
          </li>
        )
      })}
      {weeks
        .filter((w) => !held.has(w))
        .map((w) => (
          <li key={w} className="wk__cell wk__cell--empty" style={{ gridColumn: `${col.get(w)} / span 1` }} aria-label={`${day(w)}: no holder`} />
        ))}
    </ul>
  )
}

/** The season's tally: who held the title and for how many weeks, most first. */
export function TitleTally({ holders, limit = 5 }: { holders: readonly Holder<TitleRow>[]; limit?: number }) {
  return (
    <ol className="wk-tally">
      {tally(holders, (r) => r.slug)
        .slice(0, limit)
        .map((t, i) => (
          <li key={t.row.slug}>
            <a className="wk-tally__chip" href={`/player/${t.row.slug}/`}>
              <span className="wk-tally__rank">{i + 1}</span>
              <span className="wk-tally__name">{t.row.name}</span>
              <span className="wk-tally__n mono">
                {t.weeks} wk{t.weeks === 1 ? '' : 's'}
              </span>
            </a>
          </li>
        ))}
    </ol>
  )
}
