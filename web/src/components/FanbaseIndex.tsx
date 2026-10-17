// The fanbases on the leaderboard: thirty flairs on one zoomed axis, a
// league-average tick from summed counts. The toggle is local state;
// nothing about it belongs in a shared link. The heading asks the lens's
// question, so it lives here with the toggle; its last word takes the
// lens's colour as the hero's name does, and volume takes none.
import { useMemo, useState } from 'react'

import { fmtInt, fmtPct } from '../lib/format'
import { negRate, posRate, sumCounts } from '../lib/metrics'
import type { Counts } from '../lib/types'
import { DeltaDot, type DeltaDotRow } from './DeltaDot'

export interface FanRow extends Counts {
  abbr: string
  name: string
  logo: string
}

export interface FanbaseIndexProps {
  fans: FanRow[]
}

export type Metric = 'neg' | 'pos' | 'volume'

export interface MetricMeta {
  key: Metric
  label: string
  /** The question's last word, which takes the tone's colour with its question mark. */
  word: string
  tone: 'neg' | 'pos' | 'neu'
}

export const METRICS: MetricMeta[] = [
  { key: 'neg', label: 'Most negative', word: 'harshest', tone: 'neg' },
  { key: 'pos', label: 'Most positive', word: 'kindest', tone: 'pos' },
  { key: 'volume', label: 'Loudest', word: 'loudest', tone: 'neu' },
]

/** The lens's question: "Which fans are the" in bone, the word and its mark in the tone's colour. */
export function FanQuestion({ metric, id }: { metric: Metric; id?: string }) {
  const { word, tone } = METRICS.find((m) => m.key === metric)!
  return (
    <h2 id={id}>
      Which fans are the <span className={`fi__lens fi__lens--${tone}`}>{word}?</span>
    </h2>
  )
}

const VALUE: Record<Metric, (c: Counts) => number> = { neg: negRate, pos: posRate, volume: (c) => c.total }

export function FanbaseIndex({ fans }: FanbaseIndexProps) {
  const [metric, setMetric] = useState<Metric>('neg')
  const value = VALUE[metric]
  const format = metric === 'volume' ? fmtInt : (v: number) => fmtPct(v)
  const rows = useMemo<DeltaDotRow[]>(
    () =>
      fans
        .map((f) => ({ key: f.abbr, label: `${f.abbr} fans`, href: `/fanbases/${f.abbr.toLowerCase()}/`, value: value(f), n: f.total, logo: f.logo }))
        .toSorted((a, b) => b.value - a.value),
    [fans, value],
  )
  // The tick: a rate of the summed counts, or the mean volume per fanbase.
  const average = metric === 'volume' ? Math.round(sumCounts(fans).total / fans.length) : value(sumCounts(fans))
  const domain = [Math.min(...rows.map((r) => r.value)), Math.max(...rows.map((r) => r.value))] as const
  const { tone } = METRICS.find((m) => m.key === metric)!

  return (
    <div className="fi">
      <header className="fi__head">
        <p className="eyebrow">Fanbases · {fmtInt(fans.length)} flairs</p>
        <FanQuestion metric={metric} id="fans-h" />
      </header>
      <div className="fi__toggle" role="group" aria-label="Rank fanbases by">
        {METRICS.map((m) => (
          <button key={m.key} type="button" className="fi__btn mono" aria-pressed={m.key === metric} onClick={() => setMetric(m.key)}>
            {m.label}
          </button>
        ))}
      </div>
      <DeltaDot rows={rows} average={average} domain={domain} format={format} tone={tone} />
    </div>
  )
}
