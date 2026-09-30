// The court, in support: a full floor in the site's hairlines, the home
// team's name along both sidelines, its logo in gray at centre, the keys
// in mute. Only his marks: his shots, his blocks ringed on the shot they
// ended, the last seconds bright. No player, no ball: nothing in the feed
// places anyone. The ticker says what happened; this says where he shot.
import type { CSSProperties } from 'react'

import { fmtInt } from '../../lib/format'
import { COURT, type CourtMark, RECENT_SECONDS } from '../../lib/replay'

export interface CourtProps {
  marks: CourtMark[]
  /** The home team's name, along the sidelines. */
  homeName: string
  /** The home team's logo URL (first-party media), at centre. */
  logo: string
  /** His name, for the text alternative. */
  subject: string
  /** PROTOTYPE: the apron tinted by the room's lean; the property is a CSS colour or null. */
  tint?: string | null
}

const { w: W, h: H, basket: B } = COURT
const HALF = H / 2
// Court lines in tenths of a foot: the key, its circle, the restricted area, the arc and its corners.
const KEY = { long: 190, half: 80 }
const CIRCLE = 60
const RESTRICTED = 40
const ARC = 237.5
const CORNER = 220
const CORNER_X = Math.sqrt(ARC * ARC - CORNER * CORNER)
const BACKBOARD = { x: 40, half: 30 }
const RIM = 7.5
const LOGO = 120

/** One end's lines; the right end is the left mirrored across the half line. */
function End({ side }: { side: 'left' | 'right' }) {
  const transform = side === 'right' ? `translate(${W} 0) scale(-1 1)` : undefined
  return (
    <g className="court__lines" transform={transform}>
      <rect x={0} y={HALF - KEY.half} width={KEY.long} height={KEY.half * 2} />
      <circle cx={KEY.long} cy={HALF} r={CIRCLE} />
      <path d={`M ${B} ${HALF - RESTRICTED} A ${RESTRICTED} ${RESTRICTED} 0 0 1 ${B} ${HALF + RESTRICTED}`} />
      <path d={`M 0 ${HALF - CORNER} H ${B + CORNER_X} A ${ARC} ${ARC} 0 0 1 ${B + CORNER_X} ${HALF + CORNER} H 0`} />
      <line className="court__board" x1={BACKBOARD.x} x2={BACKBOARD.x} y1={HALF - BACKBOARD.half} y2={HALF + BACKBOARD.half} />
      <circle className="court__rim" cx={B} cy={HALF} r={RIM} />
    </g>
  )
}

export function Court({ marks, homeName, logo, subject, tint = null }: CourtProps) {
  const made = marks.filter((m) => m.kind === 'make').length
  const shots = marks.filter((m) => m.kind !== 'block').length
  const blocks = marks.length - shots
  const summary = `${subject}: ${fmtInt(made)} of ${fmtInt(shots)} shots made, ${fmtInt(blocks)} ${blocks === 1 ? 'block' : 'blocks'}, on ${homeName}'s floor.`
  const name = homeName.toUpperCase()
  return (
    <figure className={`court${tint ? ' court--tint' : ''}`} style={tint ? ({ '--court-tint': tint } as CSSProperties) : undefined}>
      <svg className="court__svg" viewBox={`-30 -30 ${W + 60} ${H + 60}`} role="img" aria-label={summary}>
        <rect className="court__apron" x={-30} y={-30} width={W + 60} height={H + 60} />
        <rect className="court__floor" x={0} y={0} width={W} height={H} />
        <g className="court__lines">
          <line x1={W / 2} x2={W / 2} y1={0} y2={H} />
          <circle cx={W / 2} cy={HALF} r={CIRCLE} />
        </g>
        <End side="left" />
        <End side="right" />
        {logo && <image className="court__logo" href={logo} x={W / 2 - LOGO / 2} y={HALF - LOGO / 2} width={LOGO} height={LOGO} preserveAspectRatio="xMidYMid meet" />}
        <text className="court__name" x={W / 2} y={-8} textAnchor="middle">
          {name}
        </text>
        <text className="court__name" x={W / 2} y={H + 8} textAnchor="middle" transform={`rotate(180 ${W / 2} ${H + 8})`}>
          {name}
        </text>
        {marks.map((m) => (
          <g key={m.key} className={`court__mark court__mark--${m.kind}${m.recent ? ' court__mark--recent' : ''}`}>
            <title>{m.label}</title>
            {m.kind === 'block' ? (
              <>
                <circle className="court__shot court__shot--miss" cx={m.x} cy={m.y} r={7} />
                <circle className="court__ring" cx={m.x} cy={m.y} r={14} />
              </>
            ) : (
              <circle className={`court__shot court__shot--${m.kind}`} cx={m.x} cy={m.y} r={7} />
            )}
          </g>
        ))}
      </svg>
      <figcaption className="court__cap mono">
        <span className="court__key court__key--make" /> made <span className="court__key court__key--miss" /> missed <span className="court__key court__key--block" /> blocked by him ·
        the last {fmtInt(RECENT_SECONDS)} game seconds bright
      </figcaption>
    </figure>
  )
}
