// The room over the game, and the scrubber: his negative and positive shares
// over a rolling window, drawn as far as the replay has played; his season's
// negative share dashed; the room's volume faint behind; the period bands at
// their replay widths. Pointer and arrow keys seek.
import '../../styles/replay.css'
import { type KeyboardEvent, type PointerEvent, useMemo, useRef } from 'react'

import { fmtPct } from '../../lib/format'
import { periodLabel } from '../../lib/recaps'
import { FLOW_SAMPLES, type FlowSeries } from '../../lib/replay'

export interface FlowStripProps {
  series: FlowSeries
  periodStarts: readonly { period: number; u: number }[]
  endU: number
  totalU: number
  /** His season's negative share. */
  usual: number
  u: number
  onSeek: (u: number) => void
  /** "Wembanyama", for the heading. */
  subject: string
}

const W = 1000
const H = 64
const LINE_H = 56
const VOLUME_H = 30
/** Arrow keys move this many replay seconds; Shift multiplies it. */
const STEP = 5
const BIG_STEP = 30

const fy = (v: number): number => H - 4 - v * LINE_H

function path(values: readonly (number | null)[], upTo: number): string {
  let d = ''
  let pen = false
  for (let i = 0; i <= upTo && i < values.length; i++) {
    const v = values[i]
    if (v === null || v === undefined) {
      pen = false
      continue
    }
    d += `${pen ? 'L' : 'M'}${((i / FLOW_SAMPLES) * W).toFixed(1)},${fy(v).toFixed(1)}`
    pen = true
  }
  return d
}

export function FlowStrip({ series, periodStarts, endU, totalU, usual, u, onSeek, subject }: FlowStripProps) {
  const svg = useRef<SVGSVGElement>(null)
  const fx = (t: number): number => (t / totalU) * W
  const k = Math.min(FLOW_SAMPLES, Math.floor((u / totalU) * FLOW_SAMPLES))
  const neg = useMemo(() => path(series.neg, k), [series, k])
  const pos = useMemo(() => path(series.pos, k), [series, k])
  const binW = W / series.bins.length
  const seekAt = (e: PointerEvent<SVGSVGElement>) => {
    const r = svg.current!.getBoundingClientRect()
    onSeek(((e.clientX - r.left) / r.width) * totalU)
  }
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    const step = e.shiftKey ? BIG_STEP : STEP
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') onSeek(u + step)
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') onSeek(u - step)
    else if (e.key === 'Home') onSeek(0)
    else if (e.key === 'End') onSeek(totalU)
    else return
    e.preventDefault()
  }
  return (
    <div className="flow">
      <div className="flow__head mono" aria-hidden="true">
        <span>The room on {subject}, over the game</span>
        <span className="flow__key">
          <i className="flow__key-neg" /> negative <i className="flow__key-pos" /> positive <i className="flow__key-usual" /> his season, negative
        </span>
      </div>
      <svg
        ref={svg}
        className="flow__svg"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="slider"
        tabIndex={0}
        aria-label={`Seek the replay; the room on ${subject} over the game, his season ${fmtPct(usual, 0)} negative`}
        aria-valuemin={0}
        aria-valuemax={Math.round(totalU)}
        aria-valuenow={Math.round(u)}
        aria-valuetext={`${Math.round(u)} of ${Math.round(totalU)} seconds`}
        onPointerDown={(e) => {
          svg.current!.setPointerCapture(e.pointerId)
          seekAt(e)
        }}
        onPointerMove={(e) => {
          if (e.buttons & 1) seekAt(e)
        }}
        onKeyDown={onKey}
        data-testid="flow"
      >
        {series.bins.map((b, i) => (
          <rect key={i} className="flow__bin" x={i * binW} y={H - (b / series.max) * VOLUME_H} width={binW - 1} height={(b / series.max) * VOLUME_H} />
        ))}
        {periodStarts.map((p) => (
          <line key={p.period} className="flow__period" x1={fx(p.u)} x2={fx(p.u)} y1={0} y2={H} vectorEffect="non-scaling-stroke" />
        ))}
        <line className="flow__usual" x1={0} x2={W} y1={fy(usual)} y2={fy(usual)} vectorEffect="non-scaling-stroke" />
        <path className="flow__neg" d={neg} vectorEffect="non-scaling-stroke" />
        <path className="flow__pos" d={pos} vectorEffect="non-scaling-stroke" />
        <rect className="flow__done" x={0} y={0} width={fx(u)} height={H} />
        <line className="flow__head-line" x1={fx(u)} x2={fx(u)} y1={0} y2={H} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flow__labels mono" aria-hidden="true">
        {periodStarts.map((p) => (
          <span key={p.period} style={{ left: `${(p.u / totalU) * 100}%` }}>
            {periodLabel(p.period)}
          </span>
        ))}
        <span className="flow__final" style={{ left: `${(endU / totalU) * 100}%` }}>
          FINAL
        </span>
      </div>
    </div>
  )
}
