// The one frame every share card is drawn in: the lockup and the season on
// top, the subject and its sentence in the middle, the hero bar and the n
// line along the bottom. Styles are inline because satori reads no CSS;
// colours come from the palette, sizes are stepped by rule, never per card.
// Every element with more than one child declares flex: satori's layout rule.
import type { CSSProperties, ReactNode } from 'react'

import { BODY, DISPLAY, MONO } from './fonts'
import { CARD_PAD, type Card, type Segment } from './model'
import { PALETTE } from './palette'
import { CARD_HEIGHT, CARD_WIDTH } from './render'

// The text column and the image box beside it.
const COLUMN = 660
const HEADSHOT = { width: 420, height: 307 }
const LOGO = 300
// Type sizes, stepped by length so a long name or the unofficial note still fits.
const TITLE_SIZE = (chars: number): number => (chars <= 16 ? 104 : chars <= 20 ? 84 : 64)
const SENTENCE_SIZE = (chars: number): number => (chars <= 60 ? 32 : 26)
const BAR_HEIGHT = 44
const BAR_LABEL = 15
const UNDER_LABEL = 16

const FILL: Record<Segment['key'], string> = { neg: PALETTE.heat, neu: PALETTE.neu, pos: PALETTE.ice }
const ALIGN: Record<Segment['key'], CSSProperties['justifyContent']> = { neg: 'flex-start', neu: 'center', pos: 'flex-end' }

const mono = (size: number, color: string = PALETTE.mute): CSSProperties => ({ fontFamily: MONO, fontWeight: 500, fontSize: size, color })

function Lockup({ mark, season }: { mark: string; season: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: 40 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontFamily: DISPLAY, fontWeight: 800, fontSize: 28, letterSpacing: '-0.01em', textTransform: 'uppercase' }}>
        <img src={mark} width={32} height={32} />
        <span style={{ color: PALETTE.heat }}>Court</span>
        <span style={{ color: PALETTE.ice, marginLeft: -4 }}>Sentiment</span>
      </div>
      <span style={mono(20)}>{season}</span>
    </div>
  )
}

function Stamp() {
  return (
    <span
      style={{
        ...mono(14, PALETTE.hl),
        fontWeight: 600,
        letterSpacing: '0.16em',
        textTransform: 'uppercase',
        padding: '3px 8px',
        border: `2px solid ${PALETTE.hl}`,
        transform: 'rotate(-3deg)',
        marginLeft: 16,
      }}
    >
      Unofficial
    </span>
  )
}

function Bar({ segments }: { segments: Segment[] }) {
  const cells = segments.filter((s) => s.share > 0)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', gap: 2, height: BAR_HEIGHT, background: PALETTE.ink }}>
        {cells.map((s) => (
          <div
            key={s.key}
            style={{ display: 'flex', flexBasis: `${s.share * 100}%`, alignItems: 'center', justifyContent: ALIGN[s.key], padding: '0 6px', background: FILL[s.key], overflow: 'hidden' }}
          >
            {s.labelFits && <span style={mono(BAR_LABEL, PALETTE.ink)}>{s.label}</span>}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 2, height: 22 }}>
        {cells.map((s) => (
          <div key={s.key} style={{ display: 'flex', flexBasis: `${s.share * 100}%`, justifyContent: ALIGN[s.key], overflow: 'visible' }}>
            {!s.labelFits && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}>
                <div style={{ width: 8, height: 8, background: FILL[s.key] }} />
                <span style={mono(UNDER_LABEL, PALETTE.bone2)}>{s.under}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

interface FrameProps {
  card: Card
  /** The favicon as a data URI. */
  mark: string
  /** The headshot or logo as a data URI. */
  image: string
}

function Subject({ card }: { card: Card }) {
  const eyebrow = card.kind === 'board' ? card.kicker : card.eyebrow
  const title = card.kind === 'team' ? card.title : card.name
  return (
    <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', width: COLUMN, gap: 18 }}>
      <span style={{ ...mono(20), letterSpacing: '0.04em' }}>{eyebrow}</span>
      <span style={{ fontFamily: DISPLAY, fontWeight: 800, fontSize: TITLE_SIZE(title.length), lineHeight: 0.95, letterSpacing: '-0.01em', textTransform: 'uppercase', color: PALETTE.bone }}>
        {title}
      </span>
      <span style={{ fontFamily: BODY, fontWeight: 500, fontSize: SENTENCE_SIZE(card.sentence.length), lineHeight: 1.25, color: PALETTE.bone }}>{card.sentence}</span>
    </div>
  )
}

function Picture({ card, image }: { card: Card; image: string }) {
  if (card.kind === 'team') {
    return <img src={image} width={LOGO} height={LOGO} style={{ position: 'absolute', right: 40, top: '50%', transform: 'translateY(-50%)', objectFit: 'contain' }} />
  }
  return (
    <img
      src={image}
      width={HEADSHOT.width}
      height={HEADSHOT.height}
      style={{ position: 'absolute', right: 0, bottom: 0, maskImage: `linear-gradient(to top, transparent 0%, ${PALETTE.ink} 22%)` }}
    />
  )
}

/** The card as satori's element tree. */
export function Frame({ card, mark, image }: FrameProps): ReactNode {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: CARD_WIDTH, height: CARD_HEIGHT, padding: CARD_PAD, background: PALETTE.ink, color: PALETTE.bone }}>
      <Lockup mark={mark} season={card.season} />
      <div style={{ display: 'flex', flex: 1, position: 'relative' }}>
        <Subject card={card} />
        <Picture card={card} image={image} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <Bar segments={card.segments} />
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <span style={mono(18)}>{card.nLine}</span>
          {card.stamp === 'unofficial' && <Stamp />}
        </div>
      </div>
    </div>
  )
}
