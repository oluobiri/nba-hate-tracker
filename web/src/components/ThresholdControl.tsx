// The official minimum, collapsed to one line; a slider on tap that stays
// open and loud once moved. Stops and the official value come from the
// caller, read from the manifest.
import { useId, useState } from 'react'

import { fmtInt } from '../lib/format'
import { Stamp } from './Stamp'

export interface ThresholdControlProps {
  /** Current minimum comments. */
  value: number
  official: number
  /** Ascending slider stops, the official value among them. */
  stops: readonly number[]
  ranked: number
  total: number
  onChange: (n: number) => void
  /** Start open (the style guide's open variant). */
  defaultOpen?: boolean
}

/** Collapsed: "Official · min. N comments · X of Y ranked · Adjust". Open: the slider. */
export function ThresholdControl({ value, official, stops, ranked, total, onChange, defaultOpen = false }: ThresholdControlProps) {
  const id = useId()
  const [opened, setOpened] = useState(defaultOpen)
  const custom = value !== official
  const open = opened || custom
  const index = Math.max(0, stops.indexOf(value))
  const status = `${custom ? 'Custom' : 'Official'} · min. ${fmtInt(value)} comments · ${ranked} of ${total} ranked`

  if (!open) {
    return (
      <div className="thr thr--closed">
        <button type="button" className="thr__toggle mono" onClick={() => setOpened(true)} aria-expanded={false}>
          <span>{status}</span>
          <span className="thr__adjust">Adjust</span>
        </button>
      </div>
    )
  }

  return (
    <div className={`thr thr--open${custom ? ' thr--custom' : ''}`}>
      <div className="thr__head">
        <label className="thr__status mono" htmlFor={`${id}-range`}>
          {status}
        </label>
        {custom && <Stamp kind="unofficial" />}
        {!custom && (
          <button type="button" className="thr__close mono" onClick={() => setOpened(false)} aria-expanded={true}>
            Close
          </button>
        )}
      </div>
      <input
        id={`${id}-range`}
        className="thr__range"
        type="range"
        min={0}
        max={stops.length - 1}
        step={1}
        value={index}
        aria-valuemin={stops[0]}
        aria-valuemax={stops.at(-1)}
        aria-valuenow={value}
        aria-valuetext={`minimum ${fmtInt(value)} comments`}
        onChange={(e) => onChange(stops[Number(e.target.value)] ?? official)}
      />
      <div className="thr__foot">
        <span className="mono thr__bound">{fmtInt(stops[0] ?? value)}</span>
        <button type="button" className="thr__reset mono" onClick={() => onChange(official)} disabled={!custom}>
          Reset to official
        </button>
        <span className="mono thr__bound">{fmtInt(stops.at(-1) ?? value)}</span>
      </div>
    </div>
  )
}
