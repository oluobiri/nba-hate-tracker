import { existsSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { CURRENT_SEASON } from '../site'
import { CONTRACT, type ColumnSpec, type FieldSpec, SCHEMA_VERSION } from './contract'
import { assertRecapDocument, assertRecapIdentity, recapDataHref } from './recap'
import type { RecapDocument, RecapEntry } from './types.gen'

// A one-row document fabricated from the contract itself, so the fixture
// cannot drift from the snapshot: every header field and every column gets
// a placeholder of its declared type.
function fieldValue(spec: FieldSpec, types: Record<string, Record<string, FieldSpec>>): unknown {
  switch (spec.type) {
    case 'string':
      return 'x'
    case 'int':
      return 1
    case 'float':
      return 1.5
    case 'bool':
      return true
    case 'map':
      return { k: fieldValue(spec.values!, types) }
    default:
      return objectValue(types[spec.type]!, types)
  }
}
function objectValue(fields: Record<string, FieldSpec>, types: Record<string, Record<string, FieldSpec>>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(fields).map(([f, spec]) => [f, fieldValue(spec, types)]))
}
const CELL: Record<string, unknown> = { string: 'x', int64: 1, float64: 1.5, bool: true, date: '2026-01-01', datetime: '2026-01-01T00:00:00', 'list<string>': ['x'] }
function frameValue(columns: ColumnSpec[]): Record<string, unknown[]> {
  return Object.fromEntries(columns.map((c) => [c.name, [CELL[c.dtype]]]))
}

type Doc = { header: Record<string, unknown>; frames: Record<string, Record<string, unknown[]>> }
function docFrom(mutate?: (doc: Doc) => void): Doc {
  const spec = CONTRACT.documents.recap!
  const header = objectValue(spec.header.types[spec.header.root]!, spec.header.types)
  header.schema_version = SCHEMA_VERSION
  const frames = Object.fromEntries(Object.entries(spec.frames).map(([name, f]) => [name, frameValue(f.columns)]))
  const doc = { header, frames }
  mutate?.(doc)
  return doc
}

const WHERE = 'recaps/g1-a-player.json'

describe('recapDataHref', () => {
  it('is the site endpoint for the key', () => {
    expect(recapDataHref('0042500405-victor-wembanyama')).toBe('/recaps/0042500405-victor-wembanyama/data.json')
  })
})

describe('assertRecapDocument', () => {
  it('passes a document shaped by the contract, with null where nullable', () => {
    expect(() => assertRecapDocument(docFrom(), WHERE)).not.toThrow()
    const nullable = CONTRACT.documents.recap!.frames.plays!.columns.find((c) => c.nullable)!
    expect(() => assertRecapDocument(docFrom((d) => (d.frames.plays![nullable.name] = [null])), WHERE)).not.toThrow()
  })

  it('refuses the wrong schema version', () => {
    expect(() => assertRecapDocument(docFrom((d) => (d.header.schema_version = SCHEMA_VERSION + 1)), WHERE)).toThrow(
      `${WHERE}: header.schema_version ${SCHEMA_VERSION + 1} is not the contract's ${SCHEMA_VERSION}`,
    )
  })

  it('refuses a header field that is missing, mistyped, or a map with a bad value', () => {
    expect(() => assertRecapDocument(docFrom((d) => delete d.header.slug), WHERE)).toThrow(`${WHERE}: header.slug is missing`)
    expect(() => assertRecapDocument(docFrom((d) => (d.header.player_id = 1.5)), WHERE)).toThrow(`${WHERE}: header.player_id: 1.5 is not int`)
    expect(() => assertRecapDocument(docFrom((d) => (d.header.classifiers = { sentiment: { model: 'm' } })), WHERE)).toThrow(
      `${WHERE}: header.classifiers.sentiment.prompt_version is missing`,
    )
  })

  it('refuses a frame set that differs from the contract', () => {
    expect(() => assertRecapDocument(docFrom((d) => delete d.frames.stints), WHERE)).toThrow(`${WHERE}: frames is missing stints`)
    expect(() => assertRecapDocument(docFrom((d) => (d.frames.extra = {})), WHERE)).toThrow(`${WHERE}: frames carries extra, not in the contract`)
  })

  it('refuses a missing column, an extra column and ragged lengths', () => {
    expect(() => assertRecapDocument(docFrom((d) => delete d.frames.plays!.clock), WHERE)).toThrow(`${WHERE}: frames.plays is missing column(s) clock`)
    expect(() => assertRecapDocument(docFrom((d) => (d.frames.plays!.extra = [1])), WHERE)).toThrow(
      `${WHERE}: frames.plays carries column(s) not in the contract: extra`,
    )
    expect(() => assertRecapDocument(docFrom((d) => (d.frames.plays!.clock = ['a', 'b'])), WHERE)).toThrow(
      `${WHERE}: frames.plays.clock has 2 rows, action_number has 1`,
    )
  })

  it('refuses a null in a non-nullable column and a value of the wrong dtype, naming the row', () => {
    expect(() => assertRecapDocument(docFrom((d) => (d.frames.comments!.sentiment = [null])), WHERE)).toThrow(
      `${WHERE}: frames.comments.sentiment[0] is null in a non-nullable column`,
    )
    expect(() => assertRecapDocument(docFrom((d) => (d.frames.plays!.wall_clock = ['late'])), WHERE)).toThrow(
      `${WHERE}: frames.plays.wall_clock[0]: "late" is not int64`,
    )
    expect(() => assertRecapDocument(docFrom((d) => (d.frames.plays!.shot_distance = [2])), WHERE)).not.toThrow()
  })

  it('refuses anything that is not a document', () => {
    expect(() => assertRecapDocument(null, WHERE)).toThrow(`${WHERE}: not an object`)
    expect(() => assertRecapDocument({ header: 1 }, WHERE)).toThrow(`${WHERE}: header is not an object`)
    expect(() => assertRecapDocument(docFrom((d) => ((d as { frames: unknown }).frames = [])), WHERE)).toThrow(`${WHERE}: frames is not an object`)
  })
})

describe('assertRecapIdentity', () => {
  const entry: RecapEntry = {
    file: WHERE,
    rows: 1,
    game_id: 'g1',
    attributed_player: 'A Player',
    player_id: 1,
    slug: 'a-player',
    live_n: 1,
    room_n: 1,
    by_period: {},
    swing: 0,
    minutes_diff: 0,
    population: 'live_thread',
  }
  const doc = (mutate?: (d: Doc) => void) =>
    assertRecapDocument(
      docFrom((d) => {
        Object.assign(d.header, { season: '2025-26', game_id: 'g1', slug: 'a-player', player_id: 1, attributed_player: 'A Player' })
        mutate?.(d)
      }),
      WHERE,
    )

  it('passes the file the entry describes', () => {
    expect(() => assertRecapIdentity(doc(), 'g1-a-player', entry, '2025-26')).not.toThrow()
  })

  it('refuses another season, game, player or comment count', () => {
    expect(() => assertRecapIdentity(doc(), 'g1-a-player', entry, '2024-25')).toThrow(`${WHERE}: header.season 2025-26 is not 2024-25`)
    expect(() => assertRecapIdentity(doc((d) => (d.header.game_id = 'g2')), 'g1-a-player', entry, '2025-26')).toThrow(
      `${WHERE}: header names g2-a-player, the registry key is g1-a-player`,
    )
    expect(() => assertRecapIdentity(doc((d) => (d.header.player_id = 2)), 'g1-a-player', entry, '2025-26')).toThrow(
      `${WHERE}: header names A Player (2), the registry entry A Player (1)`,
    )
    expect(() => assertRecapIdentity(doc(), 'g1-a-player', { ...entry, rows: 2 }, '2025-26')).toThrow(`${WHERE}: 1 comments, the registry entry says 2`)
  })
})

// The published files, when the repo's data directory is beside the site
// (never in CI): every one passes the assertion and matches its entry.
const RECAPS = path.resolve(__dirname, '../../../data', CURRENT_SEASON, 'dashboard/recaps')
const files = existsSync(RECAPS) ? readdirSync(RECAPS).filter((f) => f.endsWith('.json')) : []

describe.skipIf(files.length === 0)('the live recap files', () => {
  const manifest = files.length ? (JSON.parse(readFileSync(path.resolve(RECAPS, '../manifest.json'), 'utf8')) as { season: string; recaps: Record<string, RecapEntry> }) : null

  it.each(files)('%s passes the contract and its registry entry', (file) => {
    const key = file.replace(/\.json$/, '')
    const doc: RecapDocument = assertRecapDocument(JSON.parse(readFileSync(path.join(RECAPS, file), 'utf8')), `recaps/${file}`)
    expect(manifest!.recaps[key]).toBeDefined()
    expect(() => assertRecapIdentity(doc, key, manifest!.recaps[key]!, manifest!.season)).not.toThrow()
  })
})
