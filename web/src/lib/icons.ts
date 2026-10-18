// The raster icons, rendered at build from the mark (public/favicon.svg,
// bundled in by the endpoints as the cards bundle it) with the resvg the
// cards use, so the mark has one source. iOS asks for a 180 px home-screen
// icon and composites transparent corners onto black, so that one sits on
// a full ink square; the fetchers that ask for favicon.ico by convention
// get the mark at 32 and 16 in one file.
import { Resvg } from '@resvg/resvg-js'

import { pngSize } from '../cards/render'

export const TOUCH_ICON_SIZE = 180
export const FAVICON_SIZES = [32, 16] as const

const ICO_HEADER = 6
const ICO_ENTRY = 16

/** The SVG rasterised to a size × size PNG, over `background` when given, transparent otherwise. */
export function iconPng(svg: string, size: number, background?: string): Buffer {
  const resvg = new Resvg(svg, {
    fitTo: { mode: 'width', value: size },
    font: { loadSystemFonts: false },
    ...(background ? { background } : {}),
  })
  return resvg.render().asPng()
}

/** PNGs into one ICO, in the order given: a 6-byte header, a 16-byte entry per image, the PNG bytes appended. */
export function ico(pngs: readonly Uint8Array[]): Buffer {
  const directory = ICO_HEADER + ICO_ENTRY * pngs.length
  const out = Buffer.alloc(directory + pngs.reduce((n, png) => n + png.byteLength, 0))
  out.writeUInt16LE(0, 0) // reserved
  out.writeUInt16LE(1, 2) // type: icon
  out.writeUInt16LE(pngs.length, 4)
  let offset = directory
  pngs.forEach((png, i) => {
    const { width, height } = pngSize(png)
    if (width > 256 || height > 256) throw new Error(`ico: image ${i} is ${width} × ${height}, over 256`)
    const entry = ICO_HEADER + ICO_ENTRY * i
    out.writeUInt8(width % 256, entry) // 0 stands for 256
    out.writeUInt8(height % 256, entry + 1)
    out.writeUInt8(0, entry + 2) // no palette
    out.writeUInt8(0, entry + 3) // reserved
    out.writeUInt16LE(1, entry + 4) // colour planes
    out.writeUInt16LE(32, entry + 6) // bits per pixel
    out.writeUInt32LE(png.byteLength, entry + 8)
    out.writeUInt32LE(offset, entry + 12)
    out.set(png, offset)
    offset += png.byteLength
  })
  return out
}
