import { describe, expect, it } from 'vitest'

import { headshotSrcSet, headshotVariant } from './media'

describe('headshotSrcSet', () => {
  it('derives the WebP variants beside the original', () => {
    expect(headshotSrcSet('https://courtsentiment.com/media/headshots/203500.png')).toBe(
      'https://courtsentiment.com/media/headshots/203500-180.webp 180w, https://courtsentiment.com/media/headshots/203500-420.webp 420w',
    )
  })

  it('takes the widths from the caller', () => {
    expect(headshotSrcSet('x/1.png', [840])).toBe('x/1-840.webp 840w')
  })
})

describe('headshotVariant', () => {
  it('names one variant', () => {
    expect(headshotVariant('https://x/media/headshots/203500.png', 840)).toBe('https://x/media/headshots/203500-840.webp')
  })
})
