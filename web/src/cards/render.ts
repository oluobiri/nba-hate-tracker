// A card is a small element tree laid out by satori into SVG and rasterised
// by resvg into a 1200 × 630 PNG. Grayscale is an SVG filter added to the
// headshot's <image> between the two steps: satori has no CSS filter, and
// filtering the PNG on its own first costs ten times the whole card.
import { Resvg } from '@resvg/resvg-js'
import type { ReactNode } from 'react'
import satori from 'satori'

import { cardFonts } from './fonts'

export const CARD_WIDTH = 1200
export const CARD_HEIGHT = 630

// Rec. 709 luma, the same weights a browser's grayscale(1) uses.
const GRAY_FILTER =
  '<filter id="gray"><feColorMatrix type="matrix" values="0.2126 0.7152 0.0722 0 0 0.2126 0.7152 0.0722 0 0 0.2126 0.7152 0.0722 0 0 0 0 0 1 0"/></filter>'

/** Mark every <image> whose href is in `hrefs` for the grayscale filter; the filter is defined once. */
export function desaturate(svg: string, hrefs: readonly string[]): string {
  if (hrefs.length === 0) return svg
  let out = svg
  for (const href of hrefs) out = out.replaceAll(`href="${href}"`, `href="${href}" filter="url(#gray)"`)
  return out.replace(/<svg([^>]*)>/, `<svg$1>${GRAY_FILTER}`)
}

/** The card as SVG: satori's layout, with the grayscale filter on the images named in `gray`. */
export async function cardSvg(element: ReactNode, gray: readonly string[] = []): Promise<string> {
  const svg = await satori(element, { width: CARD_WIDTH, height: CARD_HEIGHT, fonts: await cardFonts() })
  return desaturate(svg, gray)
}

/** Rasterise a card's SVG at its native size. Text is already paths; no system fonts are consulted. */
export function cardPng(svg: string): Buffer {
  return new Resvg(svg, { fitTo: { mode: 'width', value: CARD_WIDTH }, font: { loadSystemFonts: false } }).render().asPng()
}

/** The whole step: element tree in, PNG bytes out. */
export async function renderCard(element: ReactNode, gray: readonly string[] = []): Promise<Buffer> {
  return cardPng(await cardSvg(element, gray))
}

/** Width and height from a PNG's IHDR chunk. */
export function pngSize(png: Uint8Array): { width: number; height: number } {
  const view = new DataView(png.buffer, png.byteOffset, png.byteLength)
  return { width: view.getUint32(16), height: view.getUint32(20) }
}
