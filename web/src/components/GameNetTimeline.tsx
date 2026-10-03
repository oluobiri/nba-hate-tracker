// Where one night sits among his games: every graded game by date, the
// room's net on each, wins filled and losses hollow, the playoffs as a band,
// his season's net dashed, this night ringed and named. SVG at build; the
// lede carries the reading and the ring's label repeats the figure.
import { fmtNet } from '../lib/net'
import type { NightPoint } from '../lib/recaps'

export interface GameNetTimelineProps {
  points: readonly NightPoint[]
  /** His season's net. */
  baseline: number
  /** The game ringed. */
  highlight: string
  /** "Finals G5", the ring's label. */
  highlightLabel: string
  /** The lede, from nightRankSentence; also the SVG's description. */
  lead: string
}

const W = 760
const H = 280
const PAD = { l: 40, r: 28, t: 34, b: 26 }
const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

const day = (date: string): number => Date.parse(`${date}T00:00:00Z`)

export function GameNetTimeline({ points, baseline, highlight, highlightLabel, lead }: GameNetTimelineProps) {
  if (points.length === 0) return <p className="nt__lead">{lead}</p>
  const t0 = day(points[0]!.date)
  const t1 = Math.max(day(points[points.length - 1]!.date), t0 + 1)
  const dom = Math.max(0.5, Math.ceil(Math.max(...points.map((p) => Math.abs(p.net)), Math.abs(baseline)) * 4) / 4)
  const x = (t: number): number => PAD.l + ((t - t0) / (t1 - t0)) * (W - PAD.l - PAD.r)
  const y = (v: number): number => PAD.t + ((dom - v) / (2 * dom)) * (H - PAD.t - PAD.b)
  const ticks: number[] = []
  for (let v = -dom; v <= dom + 1e-9; v += 0.25) ticks.push(v)
  const months: number[] = []
  for (const d = new Date(t0); d.getTime() <= t1; d.setUTCMonth(d.getUTCMonth() + 1, 1)) {
    const m = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)
    if (m >= t0) months.push(m)
  }
  const playoffs = points.filter((p) => p.playoffs)
  const me = points.find((p) => p.gameId === highlight)
  return (
    <figure className="nt">
      <p className="nt__lead">{lead}</p>
      <svg className="nt__svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={lead}>
        {playoffs.length > 0 && (
          <g>
            <rect className="nt__band" x={x(day(playoffs[0]!.date)) - 6} y={PAD.t - 6} width={W - PAD.r - x(day(playoffs[0]!.date)) + 6} height={H - PAD.t - PAD.b + 12} />
            <text className="nt__tick" x={x(day(playoffs[0]!.date))} y={PAD.t - 10}>
              PLAYOFFS
            </text>
          </g>
        )}
        {ticks.map((v) => (
          <g key={v}>
            <line className={v === 0 ? 'nt__axis' : 'nt__grid'} x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} />
            <text className="nt__tick" x={PAD.l - 8} y={y(v) + 4} textAnchor="end">
              {fmtNet(v)}
            </text>
          </g>
        ))}
        <line className="nt__base" x1={PAD.l} x2={W - PAD.r} y1={y(baseline)} y2={y(baseline)} />
        {months.map((m) => (
          <text key={m} className="nt__tick" x={x(m)} y={H - 6}>
            {MONTHS[new Date(m).getUTCMonth()]}
          </text>
        ))}
        {points.map((p) =>
          p.win ? (
            <circle key={p.gameId} className="nt__pt nt__pt--w" cx={x(day(p.date))} cy={y(p.net)} r={5}>
              <title>{p.label}</title>
            </circle>
          ) : (
            <circle key={p.gameId} className="nt__pt nt__pt--l" cx={x(day(p.date))} cy={y(p.net)} r={4.25}>
              <title>{p.label}</title>
            </circle>
          ),
        )}
        {me && (
          <g>
            <circle className="nt__ring" cx={x(day(me.date))} cy={y(me.net)} r={12} />
            <text className="nt__label" x={x(day(me.date))} y={y(me.net) + 29} textAnchor="end">
              {highlightLabel} · {fmtNet(me.net)}
            </text>
          </g>
        )}
      </svg>
      <figcaption className="nt__key mono">
        <span className="nt__key-w" /> win <span className="nt__key-l" /> loss <span className="nt__key-ring" /> this game <span className="nt__key-base" /> his season
      </figcaption>
    </figure>
  )
}
