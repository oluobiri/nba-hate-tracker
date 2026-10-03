// The recap document: the one file the site fetches at runtime. It is
// asserted against the contract's documents.recap twice, once where the
// build endpoint re-serves it and once when the island receives it, so a
// drifted file fails the build and a stale copy fails loudly. No node
// imports: this module runs in the browser.
import { type ColumnSpec, ContractError, documentOf, type FieldSpec, SCHEMA_VERSION } from './contract'
import type { RecapDocument, RecapEntry } from './types.gen'

const DOCUMENT = 'recap'

/** The same-origin path the island fetches: the build endpoint's route. */
export function recapDataHref(key: string): string {
  return `/recaps/${key}/data.json`
}

type Fail = (what: string) => ContractError

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

// JSON-side vocabulary, as the header declares it.
function checkField(fail: Fail, where: string, value: unknown, spec: FieldSpec, types: Record<string, Record<string, FieldSpec>>): void {
  if (value === null) {
    if (!spec.nullable) throw fail(`${where} is null in a non-nullable field`)
    return
  }
  const bad = () => fail(`${where}: ${JSON.stringify(value)} is not ${spec.type}`)
  switch (spec.type) {
    case 'string':
      if (typeof value !== 'string') throw bad()
      return
    case 'int':
      if (!Number.isInteger(value)) throw bad()
      return
    case 'float':
      if (typeof value !== 'number' || !Number.isFinite(value)) throw bad()
      return
    case 'bool':
      if (typeof value !== 'boolean') throw bad()
      return
    case 'map': {
      if (!isRecord(value)) throw bad()
      if (!spec.values) throw fail(`${where}: the contract declares a map without values`)
      for (const [k, v] of Object.entries(value)) checkField(fail, `${where}.${k}`, v, spec.values, types)
      return
    }
    default: {
      const fields = types[spec.type]
      if (!fields) throw fail(`${where}: the contract names an undeclared type ${spec.type}`)
      checkObject(fail, where, value, fields, types)
    }
  }
}

function checkObject(fail: Fail, where: string, value: unknown, fields: Record<string, FieldSpec>, types: Record<string, Record<string, FieldSpec>>): void {
  if (!isRecord(value)) throw fail(`${where} is not an object`)
  for (const [field, spec] of Object.entries(fields)) {
    if (!(field in value)) throw fail(`${where}.${field} is missing`)
    checkField(fail, `${where}.${field}`, value[field], spec, types)
  }
}

// Parquet-side vocabulary, as a frame's columns declare it; the values are
// JSON, so INT64 is already a number and dates are strings.
const CELL: Record<string, (v: unknown) => boolean> = {
  string: (v) => typeof v === 'string',
  int64: (v) => Number.isInteger(v),
  float64: (v) => typeof v === 'number' && Number.isFinite(v),
  bool: (v) => typeof v === 'boolean',
  date: (v) => typeof v === 'string',
  datetime: (v) => typeof v === 'string',
  'list<string>': (v) => Array.isArray(v) && v.every((s) => typeof s === 'string'),
}

function checkFrame(fail: Fail, where: string, value: unknown, columns: readonly ColumnSpec[]): void {
  if (!isRecord(value)) throw fail(`${where} is not an object of columns`)
  const names = new Set(columns.map((c) => c.name))
  const missing = columns.filter((c) => !(c.name in value)).map((c) => c.name)
  if (missing.length) throw fail(`${where} is missing column(s) ${missing.join(', ')}`)
  const extra = Object.keys(value).filter((k) => !names.has(k))
  if (extra.length) throw fail(`${where} carries column(s) not in the contract: ${extra.join(', ')}`)
  let first: { name: string; length: number } | null = null
  for (const col of columns) {
    const arr = value[col.name]
    if (!Array.isArray(arr)) throw fail(`${where}.${col.name} is not an array`)
    if (!first) first = { name: col.name, length: arr.length }
    else if (arr.length !== first.length) throw fail(`${where}.${col.name} has ${arr.length} rows, ${first.name} has ${first.length}`)
    const ok = CELL[col.dtype]
    if (!ok) throw fail(`${where}.${col.name}: unknown dtype ${JSON.stringify(col.dtype)}`)
    for (let i = 0; i < arr.length; i++) {
      const v: unknown = arr[i]
      if (v === null) {
        if (!col.nullable) throw fail(`${where}.${col.name}[${i}] is null in a non-nullable column`)
      } else if (!ok(v)) throw fail(`${where}.${col.name}[${i}]: ${JSON.stringify(v)} is not ${col.dtype}`)
    }
  }
}

/**
 * The document as the contract declares it: the header field by field, and
 * every frame with exactly its columns, each an array of one length, typed,
 * null only where nullable. Throws a ContractError naming the spot.
 */
export function assertRecapDocument(doc: unknown, where: string): RecapDocument {
  const fail: Fail = (what) => new ContractError(`${where}: ${what}`)
  const spec = documentOf(DOCUMENT)
  if (!isRecord(doc)) throw fail('not an object')
  if (!isRecord(doc.header)) throw fail('header is not an object')
  if (doc.header.schema_version !== SCHEMA_VERSION)
    throw fail(`header.schema_version ${JSON.stringify(doc.header.schema_version)} is not the contract's ${SCHEMA_VERSION}`)
  const root = spec.header.types[spec.header.root]
  if (!root) throw fail(`the contract's header root ${spec.header.root} is not declared`)
  checkObject(fail, 'header', doc.header, root, spec.header.types)

  const given = doc.frames
  if (!isRecord(given)) throw fail('frames is not an object')
  const frames = Object.keys(spec.frames)
  const missing = frames.filter((f) => !(f in given))
  if (missing.length) throw fail(`frames is missing ${missing.join(', ')}`)
  const extra = Object.keys(given).filter((f) => !(f in spec.frames))
  if (extra.length) throw fail(`frames carries ${extra.join(', ')}, not in the contract`)
  for (const frame of frames) checkFrame(fail, `frames.${frame}`, given[frame], spec.frames[frame]?.columns ?? [])
  return doc as unknown as RecapDocument
}

/** The file is the one the registry entry describes: same game, player and comment count. */
export function assertRecapIdentity(doc: RecapDocument, key: string, entry: RecapEntry, season: string): void {
  const fail = (what: string) => new ContractError(`${entry.file}: ${what}`)
  const h = doc.header
  if (h.season !== season) throw fail(`header.season ${h.season} is not ${season}`)
  if (h.game_id !== entry.game_id || h.slug !== entry.slug) throw fail(`header names ${h.game_id}-${h.slug}, the registry key is ${key}`)
  if (h.player_id !== entry.player_id || h.attributed_player !== entry.attributed_player)
    throw fail(`header names ${h.attributed_player} (${h.player_id}), the registry entry ${entry.attributed_player} (${entry.player_id})`)
  const rows = doc.frames.comments.comment_id.length
  if (rows !== entry.rows) throw fail(`${rows} comments, the registry entry says ${entry.rows}`)
}

/** The clocks the page searches by binary split never run backwards: plays by wall clock, comments by their time. */
export function assertRecapOrder(doc: RecapDocument, where: string): void {
  const check = (name: string, col: readonly number[]) => {
    for (let i = 1; i < col.length; i++) {
      if (col[i]! < col[i - 1]!) throw new ContractError(`${where}: ${name}[${i}] runs backwards (${col[i]} after ${col[i - 1]})`)
    }
  }
  check('frames.plays.wall_clock', doc.frames.plays.wall_clock)
  check('frames.plays.game_seconds', doc.frames.plays.game_seconds)
  check('frames.comments.created_utc', doc.frames.comments.created_utc)
}

/** Fetch the recap the island plays, from the site's own origin, asserted on arrival. */
export async function fetchRecap(key: string): Promise<RecapDocument> {
  const href = recapDataHref(key)
  const res = await fetch(href)
  if (!res.ok) throw new ContractError(`${href}: HTTP ${res.status}`)
  return assertRecapDocument(await res.json(), href)
}
