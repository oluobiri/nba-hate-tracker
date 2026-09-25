import { mkdtemp, mkdir, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { mediaPath, readMedia } from './assets'

const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47])

describe('mediaPath', () => {
  it('maps a first-party URL onto the local media tree', () => {
    expect(mediaPath('https://courtsentiment.com/media/headshots/1.png', '/repo/data')).toBe('/repo/data/media/headshots/1.png')
    expect(mediaPath('https://courtsentiment.com/media/logos/2.svg', '/repo/data')).toBe('/repo/data/media/logos/2.svg')
  })

  it('refuses anything outside /media/', () => {
    expect(() => mediaPath('https://courtsentiment.com/data/x.png', '/repo/data')).toThrow(/not first-party media/)
  })
})

describe('readMedia', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reads from the filesystem under a path base and returns a data URI', async () => {
    const base = await mkdtemp(path.join(tmpdir(), 'media-'))
    await mkdir(path.join(base, 'media', 'headshots'), { recursive: true })
    await writeFile(path.join(base, 'media', 'headshots', '1.png'), PNG)
    expect(await readMedia('https://courtsentiment.com/media/headshots/1.png', base)).toBe(`data:image/png;base64,${PNG.toString('base64')}`)
  })

  it('fetches once under a URL base and shares the result', async () => {
    const fetchMock = vi.fn(async () => new Response(PNG, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const url = 'https://example.test/media/logos/9.svg'
    const [a, b] = await Promise.all([readMedia(url, 'https://example.test/data'), readMedia(url, 'https://example.test/data')])
    expect(a).toBe(b)
    expect(a.startsWith('data:image/svg+xml;base64,')).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('throws on a miss instead of returning an empty image', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 404 })),
    )
    await expect(readMedia('https://example.test/media/headshots/404.png', 'https://example.test/data')).rejects.toThrow(/HTTP 404/)
  })

  it('refuses a file type the card cannot draw', async () => {
    await expect(readMedia('https://example.test/media/headshots/1.webp', 'https://example.test/data')).rejects.toThrow(/not a card image/)
  })
})
