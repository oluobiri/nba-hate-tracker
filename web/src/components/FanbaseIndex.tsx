// The fanbase index: thirty flairs on one zoomed axis, a league-average
// tick from summed counts. The toggle is local state; nothing about it
// belongs in a shared link.
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

type Metric = 'neg' | 'pos' | 'volume'

const METRICS: { key: Metric; label: string; tone: 'neg' | 'pos' | 'neu' }[] = [
  { key: 'neg', label: 'Most negative', tone: 'neg' },
  { key: 'pos', label: 'Most positive', tone: 'pos' },
  { key: 'volume', label: 'Loudest', tone: 'neu' },
]

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
  const average = metric === 'volume' ? sumCounts(fans).total / fans.length : value(sumCounts(fans))
  const domain = [Math.min(...rows.map((r) => r.value)), Math.max(...rows.map((r) => r.value))] as const
  const tone = METRICS.find((m) => m.key === metric)!.tone

  return (
    <div className="fi">
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
