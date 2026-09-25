// The card's fonts: the site's three families, read once from the installed
// @fontsource packages. WOFF, not WOFF2, which satori cannot parse.
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'

import type { Font, FontWeight } from 'satori'

export const DISPLAY = 'Barlow Condensed'
export const BODY = 'Barlow'
export const MONO = 'IBM Plex Mono'

const FILES: { name: string; pkg: string; stem: string; weight: FontWeight }[] = [
  { name: DISPLAY, pkg: '@fontsource/barlow-condensed', stem: 'barlow-condensed', weight: 800 },
  { name: BODY, pkg: '@fontsource/barlow', stem: 'barlow', weight: 400 },
  { name: BODY, pkg: '@fontsource/barlow', stem: 'barlow', weight: 500 },
  { name: MONO, pkg: '@fontsource/ibm-plex-mono', stem: 'ibm-plex-mono', weight: 500 },
  { name: MONO, pkg: '@fontsource/ibm-plex-mono', stem: 'ibm-plex-mono', weight: 600 },
]

const require = createRequire(import.meta.url)

let pending: Promise<Font[]> | undefined

/** Every font the card frame uses, loaded once per process. */
export function cardFonts(): Promise<Font[]> {
  pending ??= Promise.all(
    FILES.map(async (f) => ({
      name: f.name,
      weight: f.weight,
      style: 'normal' as const,
      data: await readFile(require.resolve(`${f.pkg}/files/${f.stem}-latin-${f.weight}-normal.woff`)),
    })),
  )
  return pending
}
