// Net sentiment as the recap page prints it: the positive share minus the
// negative share, in points, coloured by its strength. The curve is linear to
// full heat at −100 and full ice at +100; this is the one place to change it.
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

/** The same colour as a custom property, for a fill rather than text. */
export const netFill = (v: number | null): CSSProperties => ({ '--net-color': netColor(v) }) as CSSProperties
