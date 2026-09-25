// The share card is rasterised outside the browser and cannot read CSS, so
// it carries the token values as literals. palette.test.ts pins each one to
// tokens.css: a token change fails there until the card follows.
export const PALETTE = {
  ink: '#0b0b0d',
  surface: '#17171b',
  line: '#2a2a31',
  bone: '#ede8dc',
  bone2: '#c9c4b8',
  mute: '#8b887f',
  heat: '#ff3d1f',
  ice: '#5cc8ff',
  neu: '#a8a497',
  hl: '#ffd21f',
} as const

export type PaletteKey = keyof typeof PALETTE
