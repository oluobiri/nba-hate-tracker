// The hand check's gaps on a Δ axis: per class, the classifier's share of the
// sample minus the hand labels' share, with its margin. Two forms in one
// SVG pair: wide puts the figures beside the row, narrow puts them over it.
import { fmtSigned } from '../lib/format'
import type { GapRow } from '../lib/method'
import type { Sentiment } from '../lib/types'

export interface GapChartProps {
  rows: readonly GapRow[]
  domain: readonly [number, number]
  ticks: readonly number[]
  /** What the zero line stands for ("Same share as the hand labels"). */
  zeroLabel: string
  caption: string
}

const NAME: Record<Sentiment, string> = { neg: 'Negative', neu: 'Neutral', pos: 'Positive' }
const CALL = { within: 'within the margin', outside: 'outside the margin' } as const

const WIDE = { w: 700, left: 90, axis: 380, rowH: 34, top: 26 }
const NARROW = { w: 360, left: 0, axis: 360, rowH: 58, top: 30 }

const figure = (r: GapRow): string => `${fmtSigned(r.gap)} ± ${(100 * r.margin).toFixed(1)}`

function Form({ rows, domain, ticks, zeroLabel, narrow }: Omit<GapChartProps, 'caption'> & { narrow: boolean }) {
  const { w, left, axis, rowH, top } = narrow ? NARROW : WIDE
  const [lo, hi] = domain
  const x = (v: number): number => left + ((v - lo) / (hi - lo)) * axis
  const bottom = top + rowH * rows.length
  return (
    <svg className={`gapchart__${narrow ? 'narrow' : 'wide'}`} viewBox={`0 0 ${w} ${bottom + 24}`} aria-hidden="true">
      {ticks.map((t) => (
        <g key={t}>
          <line className="gapchart__grid" x1={x(t)} x2={x(t)} y1={top - 6} y2={bottom} />
          <text className="gapchart__axis" x={x(t)} y={bottom + 16} textAnchor="middle">
            {fmtSigned(t, 0)}
          </text>
        </g>
      ))}
      <line className="gapchart__zero" x1={x(0)} x2={x(0)} y1={top - 10} y2={bottom} />
      <text className="gapchart__axis" x={x(0)} y={top - 14} textAnchor="middle">
        {zeroLabel}
      </text>
      {rows.map((r, i) => {
        const rowTop = top + rowH * i
        const y = narrow ? rowTop + rowH - 14 : rowTop + rowH / 2
        const callClass = `gapchart__call${r.call === 'outside' ? ' gapchart__call--out' : ''}`
        return (
          <g key={r.cls}>
            {narrow ? (
              <>
                <rect className="gapchart__mask" x={0} y={rowTop + 6} width={w} height={18} />
                <text className="gapchart__lab" x={0} y={rowTop + 20}>
                  {NAME[r.cls]}
                </text>
                <text className="gapchart__val" x={w} y={rowTop + 20} textAnchor="end">
                  {figure(r)}
                </text>
                <text className={callClass} x={w} y={rowTop + 36} textAnchor="end">
                  {CALL[r.call]}
                </text>
              </>
            ) : (
              <>
                <text className="gapchart__lab" x={0} y={y + 4}>
                  {NAME[r.cls]}
                </text>
                <text className="gapchart__val" x={left + axis + 12} y={y + 4}>
                  {figure(r)}
                </text>
                <text className={callClass} x={left + axis + 104} y={y + 4}>
                  {CALL[r.call]}
                </text>
              </>
            )}
            <line className="gapchart__range" x1={x(r.gap - r.margin)} x2={x(r.gap + r.margin)} y1={y} y2={y} />
            <circle className={`gapchart__dot gapchart__dot--${r.cls}`} cx={x(r.gap)} cy={y} r={5} />
          </g>
        )
      })}
    </svg>
  )
}

/** Classifier share minus manual share, per class, on one Δ axis with its margins; wording chosen by the data. */
export function GapChart(props: GapChartProps) {
  const spoken = props.rows.map((r) => `${NAME[r.cls]} ${figure(r)} points, ${CALL[r.call]}`).join('; ')
  return (
    <figure className="gapchart" role="img" aria-label={`Classifier share minus hand-label share, per class: ${spoken}.`}>
      <Form {...props} narrow={false} />
      <Form {...props} narrow />
      <figcaption className="gapchart__caption">{props.caption}</figcaption>
    </figure>
  )
}
