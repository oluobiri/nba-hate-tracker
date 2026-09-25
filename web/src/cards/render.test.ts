import { Resvg } from '@resvg/resvg-js'
import { createElement } from 'react'
import { describe, expect, it } from 'vitest'

import { BODY } from './fonts'
import { CARD_HEIGHT, CARD_WIDTH, cardSvg, desaturate, pngSize, renderCard } from './render'

// A 1 × 1 pure-red PNG, made by resvg itself so no fixture file is needed.
const RED = new Resvg('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="#ff0000"/></svg>').render().asPng()
const RED_URI = `data:image/png;base64,${RED.toString('base64')}`

const card = (src: string) =>
  createElement(
    'div',
    { style: { display: 'flex', width: CARD_WIDTH, height: CARD_HEIGHT, background: '#000000' } },
    createElement('img', { src, width: 100, height: 100 }),
    createElement('span', { style: { fontFamily: BODY, fontSize: 24, color: '#ffffff' } }, 'fixture'),
  )

describe('desaturate', () => {
  it('defines the filter once and marks only the named images', () => {
    const svg = '<svg width="2" height="2"><image href="a"/><image href="b"/></svg>'
    const out = desaturate(svg, ['a'])
    expect(out.match(/<filter id="gray">/g)).toHaveLength(1)
    expect(out).toContain('<image href="a" filter="url(#gray)"/>')
    expect(out).toContain('<image href="b"/>')
  })

  it('leaves the SVG alone when nothing is named', () => {
    expect(desaturate('<svg></svg>', [])).toBe('<svg></svg>')
  })
})

// The RGB at (50, 50), inside the fixture's image.
const pixel = (svg: string) => {
  const { pixels } = new Resvg(svg, { font: { loadSystemFonts: false } }).render()
  const i = (50 * CARD_WIDTH + 50) * 4
  return [pixels[i], pixels[i + 1], pixels[i + 2]]
}

describe('renderCard', () => {
  it('rasterises a 1200 × 630 PNG', async () => {
    const png = await renderCard(card(RED_URI))
    expect(png.subarray(1, 4).toString()).toBe('PNG')
    expect(pngSize(png)).toEqual({ width: CARD_WIDTH, height: CARD_HEIGHT })
  })

  it('renders a named image in grayscale and the others in colour', async () => {
    const colour = pixel(await cardSvg(card(RED_URI)))
    const gray = pixel(await cardSvg(card(RED_URI), [RED_URI]))
    expect(colour).toEqual([255, 0, 0])
    expect(gray[0]).toBe(gray[1])
    expect(gray[1]).toBe(gray[2])
    expect(gray[0]).toBeGreaterThan(40)
  })
})
