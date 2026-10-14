// Game Score against the room's net: one point per game the room talked
// about. Wins filled bone, losses hollow; zero as the axis, his season's
// net as a dashed rule. SVG at build; the games table below is the
// accessible equivalent.
import type { ScatterPoint } from '../lib/games'
import { fmtInt } from '../lib/format'
import { fmtNet } from '../lib/net'

export interface GameScatterProps {
  points: readonly ScatterPoint[]
  /** His season's net. */
  baseline: number
  /** The plain-words lead, from scatterLead. */
  lead: string
  r: number | null
}

const W = 320
const H = 240
const PAD = { l: 40, r: 12, t: 12, b: 26 }

const nice = (v: number, step: number, up: boolean): number => (up ? Math.ceil(v / step) * step : Math.floor(v / step) * step)

export function GameScatter({ points, baseline, lead, r }: GameScatterProps) {
  const xs = points.map((p) => p.x)
  const x0 = Math.min(0, nice(Math.min(...xs), 10, false))
  const x1 = Math.max(x0 + 10, nice(Math.max(...xs), 10, true))
  // The net axis is symmetric, a quarter past the widest lean, never narrower than ±50.
  const dom = Math.max(0.5, nice(Math.max(Math.abs(baseline), ...points.map((p) => Math.abs(p.y))), 0.25, true))
  const sx = (x: number): number => PAD.l + ((x - x0) / (x1 - x0)) * (W - PAD.l - PAD.r)
  const sy = (y: number): number => PAD.t + ((dom - y) / (2 * dom)) * (H - PAD.t - PAD.b)
  const xTicks: number[] = []
  for (let t = x0; t <= x1; t += 10) xTicks.push(t)
  const yTicks: number[] = []
  for (let t = -dom; t <= dom + 1e-9; t += 0.25) yTicks.push(t)
  const rText = r === null ? 'r n/a' : `r = ${r < 0 ? '−' : ''}${Math.abs(r).toFixed(2)}`

  return (
    <figure className="sc">
      <p className="sc__lead">{lead}</p>
      <div className="sc__plot">
        <span className="sc__y mono" aria-hidden="true">
          net
        </span>
        <svg
          className="sc__svg"
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`${fmtInt(points.length)} games: Game Score across, net sentiment up, his season's net ${fmtNet(baseline)} marked.`}
        >
          {yTicks.map((t) => (
            <g key={`y${t}`}>
              <line className="sc__grid" x1={PAD.l} x2={W - PAD.r} y1={sy(t)} y2={sy(t)} />
              <text className="sc__tick" x={PAD.l - 5} y={sy(t)} textAnchor="end" dominantBaseline="middle">
                {fmtNet(t)}
              </text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={`x${t}`} className="sc__tick" x={sx(t)} y={H - PAD.b + 12} textAnchor="middle">
              {t}
            </text>
          ))}
          <line className="sc__axis" x1={PAD.l} x2={W - PAD.r} y1={sy(0)} y2={sy(0)} />
          <line className="sc__base" x1={PAD.l} x2={W - PAD.r} y1={sy(baseline)} y2={sy(baseline)} />
          <text className="sc__base-label" x={W - PAD.r} y={sy(baseline) - 3} textAnchor="end">
            his season {fmtNet(baseline)}
          </text>
          {points.map((p) => (
            <circle key={p.gameId} className={`sc__pt sc__pt--${p.win ? 'w' : 'l'}`} cx={sx(p.x)} cy={sy(p.y)} r={3.5}>
              <title>{p.label}</title>
            </circle>
          ))}
        </svg>
        <span className="sc__x mono" aria-hidden="true">
          Game Score →
        </span>
      </div>
      <figcaption className="sc__cap mono">
        {rText} · {fmtInt(points.length)} games · <span className="sc__key sc__key--w" /> win <span className="sc__key sc__key--l" /> loss
      </figcaption>
    </figure>
  )
}
