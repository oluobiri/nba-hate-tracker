import { Resvg } from '@resvg/resvg-js'
import { describe, expect, it } from 'vitest'

import mark from '../../public/favicon.svg?raw'
import { pngSize } from '../cards/render'
import { FAVICON_SIZES, TOUCH_ICON_SIZE, ico, iconPng } from './icons'

// A 4 × 4 SVG with a transparent top-left quadrant and a red rest.
const QUADRANT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><path fill="#ff0000" d="M2 0h2v4H0V2h2Z"/></svg>'

/** RGBA at the top-left pixel of a PNG, read by rendering it as an <image> at its own size. */
const corner = (png: Buffer): number[] => {
  const { width, height } = pngSize(png)
  const uri = `data:image/png;base64,${png.toString('base64')}`
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><image href="${uri}" width="${width}" height="${height}"/></svg>`
  return [...new Resvg(svg).render().pixels.subarray(0, 4)]
}

describe('iconPng', () => {
  it('renders the SVG at the size asked, transparent where it is', () => {
    const png = iconPng(QUADRANT, 16)
    expect(pngSize(png)).toEqual({ width: 16, height: 16 })
    expect(corner(png)[3]).toBe(0)
  })

  it('lays a background under the SVG when given one', () => {
    const png = iconPng(QUADRANT, 16, '#0000ff')
    expect(corner(png)).toEqual([0, 0, 255, 255])
  })

  it('renders the mark at the touch-icon and favicon sizes', () => {
    expect(pngSize(iconPng(mark, TOUCH_ICON_SIZE))).toEqual({ width: 180, height: 180 })
    for (const size of FAVICON_SIZES) expect(pngSize(iconPng(mark, size))).toEqual({ width: size, height: size })
  })
})

describe('ico', () => {
  const pngs = FAVICON_SIZES.map((size) => iconPng(QUADRANT, size))
  const file = ico(pngs)

  it('writes the header and one entry per image', () => {
    expect(file.readUInt16LE(0)).toBe(0)
    expect(file.readUInt16LE(2)).toBe(1)
    expect(file.readUInt16LE(4)).toBe(2)
    expect(file.byteLength).toBe(6 + 16 * 2 + pngs[0]!.byteLength + pngs[1]!.byteLength)
  })

  it('names each image size and places its bytes where the entry points', () => {
    let offset = 6 + 16 * 2
    pngs.forEach((png, i) => {
      const entry = 6 + 16 * i
      expect([file.readUInt8(entry), file.readUInt8(entry + 1)]).toEqual([FAVICON_SIZES[i], FAVICON_SIZES[i]])
      expect(file.readUInt16LE(entry + 6)).toBe(32)
      expect(file.readUInt32LE(entry + 8)).toBe(png.byteLength)
      expect(file.readUInt32LE(entry + 12)).toBe(offset)
      expect(file.subarray(offset, offset + png.byteLength).equals(png)).toBe(true)
      offset += png.byteLength
    })
  })

  it('refuses an image over 256', () => {
    expect(() => ico([iconPng(QUADRANT, 300)])).toThrow('over 256')
  })
})
