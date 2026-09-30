// The scrubber, drawn on wall time: each period a band at its real width,
// each break the card's width, so a long fourth quarter reads as one. The
// range input is the control; the bands are the picture under it. The lag
// sits beside it, as the brief asks.
import { fromPlayback, type Timeline, toPlayback } from '../../lib/clock'

export interface ScrubberProps {
  tl: Timeline
  t: number
  /** "Q3 04:12 · 9:47 PM ET", for the slider's value text. */
  valueText: string
  /** "about a minute"; null when the lag is unmeasured. */
  lag: string | null
  onSeek?: (t: number) => void
}

export function Scrubber({ tl, t, valueText, lag, onSeek }: ScrubberProps) {
  return (
    <div className="scrub">
      <div className="scrub__bands" aria-hidden="true">
        {tl.segments.map((s) => (
          <span key={`${s.kind}${s.period}`} className={`scrub__band scrub__band--${s.kind}`} style={{ flexGrow: s.p1 - s.p0 }}>
            {s.kind === 'period' ? s.label : ''}
          </span>
        ))}
      </div>
      <input
        type="range"
        className="scrub__range"
        min={0}
        max={tl.length}
        step={1}
        value={toPlayback(tl, t)}
        aria-label="Moment in the game"
        aria-valuetext={valueText}
        onChange={(e) => onSeek?.(fromPlayback(tl, Number(e.currentTarget.value)))}
        disabled={!onSeek}
      />
      {lag && <p className="scrub__lag mono">± {lag}, the room's reaction lag</p>}
    </div>
  )
}
