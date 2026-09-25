// First-party media, read at build for the cards: a URL base fetches it, a
// filesystem base reads the same path under <base>/media/. Each file is read
// once per build. A miss throws and fails the build: a card without its
// headshot would sit in every share preview's cache until the next drop.
import { readFile } from 'node:fs/promises'
import path from 'node:path'

import { isUrl, resolveDataBase } from '../data/env'

const TYPES: Record<string, string> = { '.png': 'image/png', '.svg': 'image/svg+xml' }

const cache = new Map<string, Promise<string>>()

/** "https://…/media/headshots/1.png" under a filesystem base → "<base>/media/headshots/1.png". */
export function mediaPath(url: string, base: string): string {
  const { pathname } = new URL(url)
  if (!pathname.startsWith('/media/')) throw new Error(`${url}: not first-party media`)
  return path.resolve(base, 'media', pathname.slice('/media/'.length))
}

async function fetchBytes(url: string): Promise<ArrayBuffer> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`)
  return res.arrayBuffer()
}

async function load(url: string, base: string): Promise<string> {
  const type = TYPES[path.extname(new URL(url).pathname)]
  if (!type) throw new Error(`${url}: not a card image`)
  const bytes: Uint8Array = isUrl(base) ? new Uint8Array(await fetchBytes(url)) : await readFile(mediaPath(url, base))
  return `data:${type};base64,${Buffer.from(bytes).toString('base64')}`
}

/** The media file as a data URI, for satori. */
export function readMedia(url: string, base: string = resolveDataBase()): Promise<string> {
  const key = `${base} ${url}`
  let pending = cache.get(key)
  if (!pending) {
    pending = load(url, base)
    cache.set(key, pending)
  }
  return pending
}

/** Start every read now, so the endpoints find their images cached instead of fetching one card at a time. A failure resurfaces on the read. */
export function warmMedia(urls: Iterable<string>, base: string = resolveDataBase()): void {
  for (const url of urls) readMedia(url, base).catch(() => undefined)
}
