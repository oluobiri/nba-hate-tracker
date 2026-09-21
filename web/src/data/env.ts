// Where the published contract is read from. DATA_BASE is shell-only
// (astro build does not load web/.env): a URL selects the published
// layout <base>/season=<season>/, a filesystem path the repo's local
// layout <base>/<season>/dashboard/. Shared by Astro frontmatter and
// the codegen script, so it stays free of Astro imports.
import { readFile } from 'node:fs/promises'
import path from 'node:path'

export const PRODUCTION_DATA_BASE = 'https://courtsentiment.com/data'

export interface SeasonLocation {
  kind: 'url' | 'file'
  root: string
}

export function resolveDataBase(env: NodeJS.ProcessEnv = process.env): string {
  return env.DATA_BASE?.trim() || PRODUCTION_DATA_BASE
}

export function isUrl(base: string): boolean {
  return /^https?:\/\//.test(base)
}

export function seasonLocation(season: string, base: string = resolveDataBase()): SeasonLocation {
  if (isUrl(base)) return { kind: 'url', root: `${base.replace(/\/+$/, '')}/season=${season}` }
  return { kind: 'file', root: path.resolve(base, season, 'dashboard') }
}

export function locate(loc: SeasonLocation, file: string): string {
  return loc.kind === 'url' ? `${loc.root}/${file}` : path.join(loc.root, file)
}

export async function readBytes(loc: SeasonLocation, file: string): Promise<ArrayBuffer> {
  const where = locate(loc, file)
  if (loc.kind === 'file') {
    const buf = await readFile(where)
    return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer
  }
  const res = await fetch(where)
  if (!res.ok) throw new Error(`${where}: HTTP ${res.status}`)
  return res.arrayBuffer()
}

export async function readJson<T = unknown>(loc: SeasonLocation, file: string): Promise<T> {
  const bytes = await readBytes(loc, file)
  return JSON.parse(new TextDecoder().decode(bytes)) as T
}
