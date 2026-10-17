// Net sentiment as the recap page prints it: the positive share minus the
// negative share, in points, coloured by its strength. Two rules, both linear
// from bone: a game's net runs to full heat at −100 and full ice at +100; a
// player's season runs to full heat at the season's lowest player and full
// ice at its highest, since no player reaches ±100 and the game ramp leaves
// every player in the pale middle. This is the one place to change either.
import type { CSSProperties } from 'react'

import { fmtSigned } from './format'
import { netSentiment } from './metrics'
import type { Counts } from './types'

/** Net as a fraction, null when there is nothing to count. */
export const netOf = (c: Counts): number | null => (c.total ? netSentiment(c) : null)

/** "+12", "−30", "0"; "—" for nothing. */
export const fmtNet = (v: number | null): string => (v === null ? '—' : fmtSigned(v, 0).replace('-', '−'))

/** The tone a net figure takes: heat below zero, ice above, bone at nothing. */
export const netTone = (v: number | null): 'neg' | 'pos' | 'neu' => (v === null || Math.round(v * 100) === 0 ? 'neu' : v < 0 ? 'neg' : 'pos')

/** The figure's colour: bone at zero, mixed toward heat or ice by the lean's strength. */
export function netColor(v: number | null): string {
  if (v === null) return 'var(--bone)'
  const strength = Math.round(Math.min(1, Math.abs(v)) * 100)
  if (strength === 0) return 'var(--bone)'
  return `color-mix(in srgb, var(--bone), var(${v < 0 ? '--heat' : '--ice'}) ${strength}%)`
}

export const netStyle = (v: number | null): CSSProperties => ({ color: netColor(v) })

/** The season's player extremes, nets as fractions: lo at or below zero, hi at or above. */
export interface PlayerNetRange {
  lo: number
  hi: number
}

/** The lowest and highest player net of the season, from counts; a side no player reaches falls back to the game rule's ±1. */
export function playerNetRange(rows: readonly Counts[]): PlayerNetRange {
  const nets = rows.map(netSentiment)
  const lo = Math.min(0, ...nets)
  const hi = Math.max(0, ...nets)
  return { lo: lo < 0 ? lo : -1, hi: hi > 0 ? hi : 1 }
}

/** The player rule: bone at zero, full heat at the season's lowest player, full ice at its highest, each side on its own scale; past the range clamps. */
export function playerNetColor(v: number | null, range: PlayerNetRange): string {
  if (v === null) return 'var(--bone)'
  const strength = Math.round(Math.min(1, v < 0 ? v / range.lo : v / range.hi) * 100)
  if (strength === 0) return 'var(--bone)'
  return `color-mix(in srgb, var(--bone), var(${v < 0 ? '--heat' : '--ice'}) ${strength}%)`
}

/** The same colour as a custom property, for a fill rather than text. */
export const netFill = (v: number | null): CSSProperties => ({ '--net-color': netColor(v) }) as CSSProperties
