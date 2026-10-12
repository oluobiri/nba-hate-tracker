// Where people talked, week by week: stacked bars in seven neutral tones,
// a key of radios that lights one band across the season (CSS reads the
// checked radio; no script), and every week a focusable column whose
// readout gives its mix. Volume is not sentiment: no heat or ice here.
import type { CSSProperties } from 'react'

import { fmtInt, fmtPct } from '../lib/format'
import { addDays, NIGHT_PHASE_LABELS, type Weekly } from '../lib/season'
import { weekLabel } from '../lib/weeks'

export interface VolumeBandsProps {
  weekly: Weekly
  /** The last night with comments, so a week past it reads as partial. */
  lastDay: string
}

// The bar's share of its column, and the grid's step.
const BAR = 0.84
const STEP = 25_000
// The phase runs under the axis are short: the ends are narrow.
const RUN_LABELS: Record<string, string> = { ...NIGHT_PHASE_LABELS, pre: 'Pre', off: 'Off' }

export function VolumeBands({ weekly, lastDay }: VolumeBandsProps) {
  const { spine, bands, totals, phases, runs } = weekly
  const n = spine.length
  const top = Math.max(STEP, Math.ceil(Math.max(...totals) / STEP) * STEP)
  const y = (v: number): number => (v / top) * 100
  const colW = 100 / n
  const ticks: number[] = []
  for (let t = STEP; t <= top; t += STEP) ticks.push(t)
  // A month label on the week holding the first of a month, after the first week.
  const months = spine.flatMap((w, k) => {
    for (let j = 0; j < 7; j++) {
      const d = addDays(w.slice(0, 10), j)
      if (d.endsWith('-01') && k > 0) return [{ k, label: new Date(Date.parse(d)).toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' }) }]
    }
    return []
  })
  const weekText = (k: number): string => {
    const total = totals[k]!
    const head = `Week of ${weekLabel(spine[k]!)}, ${NIGHT_PHASE_LABELS[phases[k]!].toLowerCase()}`
    if (!total) return `${head}: no comments.`
    return `${head}: ${fmtInt(total)} comments; ${bands.map((b) => `${b.label} ${fmtPct(b.n[k]! / total, 0)}`).join(', ')}.`
  }
  const partial = (k: number): boolean => addDays(spine[k]!.slice(0, 10), 6) > lastDay

  return (
    <figure className="vb fig">
      <fieldset className="bands">
        <legend className="visually-hidden">Light one room across the season</legend>
        <label className="bands__key">
          <input type="radio" name="band" value="" defaultChecked />
          <span>All rooms</span>
        </label>
        {bands.map((b) => (
          <label key={b.key} className="bands__key">
            <input type="radio" name="band" value={b.key} />
            <i className={`band-${b.key}`} />
            <span>{b.label}</span>
          </label>
        ))}
      </fieldset>
      <div className="ch vb__chart">
        <div className="ch__grid" aria-hidden="true">
          {ticks.map((t, i) => (
            <span key={t} className="ch__tick-row" style={{ bottom: `${y(t)}%` }}>
              <span className="ch__tick-label">
                {t / 1000}k{i === ticks.length - 1 && <em> a week</em>}
              </span>
            </span>
          ))}
        </div>
        <svg className="ch__svg vb__svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {spine.map((w, k) => {
            let run = 0
            return bands.map((b) => {
              const lo = run
              run += b.n[k]!
              return <rect key={`${w}${b.key}`} className={`band-${b.key}`} x={(k * colW + colW * ((1 - BAR) / 2)).toFixed(3)} width={(colW * BAR).toFixed(3)} y={(100 - y(run)).toFixed(3)} height={Math.max(0, y(run) - y(lo) - 0.3).toFixed(3)} />
            })
          })}
        </svg>
        <ol className="ch__cols" aria-label="Comments about players, week by week" style={{ '--n': n } as CSSProperties}>
          {spine.map((w, k) => (
            <li key={w} className="ch__col" tabIndex={0} role="group" aria-label={weekText(k)} style={{ '--i': k, left: `${k * colW}%` } as CSSProperties}>
              <span className="ch__tip ro" aria-hidden="true">
                <span className="ro__head">
                  <b>
                    Week of {weekLabel(w)}
                    {partial(k) && ' (partial)'}
                  </b>
                  <span className="mono">{NIGHT_PHASE_LABELS[phases[k]!]}</span>
                  <span className="mono">{fmtInt(totals[k]!)} comments</span>
                </span>
                <span className="ro__line">{totals[k] ? bands.map((b) => `${b.label} ${fmtPct(b.n[k]! / totals[k]!, b.n[k]! / totals[k]! < 0.01 ? 1 : 0)}`).join(' · ') : 'No comments.'}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>
      <ol className="months" aria-hidden="true">
        {months.map((m) => (
          <li key={m.k} style={{ left: `${m.k * colW}%` }}>
            {m.label}
          </li>
        ))}
      </ol>
      <ol className="phases" aria-hidden="true">
        {runs.map((r) => (
          <li key={r.from} style={{ left: `${r.from * colW}%`, width: `${(r.to - r.from + 1) * colW - 0.4}%` }}>
            {RUN_LABELS[r.phase]}
          </li>
        ))}
      </ol>
      <div className="ro ro--reserve ro--week" aria-hidden="true">
        <p className="ro__hint">Tap a room in the key to light it up across the season. Hover or tap a week for its mix.</p>
      </div>
      <figcaption className="visually-hidden">Comments about players by the kind of post they sit under, one bar per week; the key lights one room.</figcaption>
    </figure>
  )
}
