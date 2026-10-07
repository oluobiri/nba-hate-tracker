import { describe, expect, it } from 'vitest'

import type { ContractSchema } from '../src/data/contract'
import { documentTypeName, renderTypes, rowTypeName } from './render-types'

const fixture: ContractSchema = {
  schema_version: 5,
  tables: {
    player_overall: {
      columns: [
        { name: 'attributed_player', dtype: 'string', nullable: false },
        { name: 'player_id', dtype: 'int64', nullable: false },
        { name: 'neg_rate', dtype: 'float64', nullable: false },
        { name: 'qualified', dtype: 'bool', nullable: false },
        { name: 'birth_date', dtype: 'date', nullable: true },
        { name: 'week', dtype: 'datetime', nullable: false },
        { name: 'aliases', dtype: 'list<string>', nullable: false },
      ],
    },
    teams: { columns: [{ name: 'team', dtype: 'string', nullable: false }] },
  },
  manifest: {
    root: 'Manifest',
    types: {
      Manifest: {
        schema_version: { type: 'int', nullable: false },
        rules: { type: 'Rules', nullable: false },
        snapshots: { type: 'map', nullable: false, values: { type: 'string', nullable: true } },
        tables: { type: 'map', nullable: false, values: { type: 'TableEntry', nullable: false } },
      },
      Rules: { threshold: { type: 'int', nullable: false }, share: { type: 'float', nullable: true } },
      TableEntry: { file: { type: 'string', nullable: false }, live: { type: 'bool', nullable: false } },
    },
  },
  documents: {},
}

// A document whose header repeats a manifest type, shape for shape.
const withRecap: ContractSchema = {
  ...fixture,
  manifest: {
    root: 'Manifest',
    types: {
      ...fixture.manifest.types,
      ClassifierIdentity: { model: { type: 'string', nullable: false }, prompt_version: { type: 'string', nullable: false } },
    },
  },
  documents: {
    recap: {
      header: {
        root: 'RecapHeader',
        types: {
          RecapHeader: {
            schema_version: { type: 'int', nullable: false },
            classifiers: { type: 'map', nullable: false, values: { type: 'ClassifierIdentity', nullable: false } },
          },
          ClassifierIdentity: { model: { type: 'string', nullable: false }, prompt_version: { type: 'string', nullable: false } },
        },
      },
      frames: {
        periods: { columns: [{ name: 'period', dtype: 'int64', nullable: false }] },
        plays: {
          columns: [
            { name: 'clock', dtype: 'string', nullable: false },
            { name: 'made', dtype: 'bool', nullable: true },
          ],
        },
      },
    },
  },
}

describe('rowTypeName', () => {
  it('pascal-cases the table name and appends Row', () => {
    expect(rowTypeName('player_fan_team')).toBe('PlayerFanTeamRow')
    expect(rowTypeName('teams')).toBe('TeamsRow')
  })
})

describe('documentTypeName', () => {
  it('pascal-cases the document name', () => {
    expect(documentTypeName('recap')).toBe('Recap')
    expect(documentTypeName('season_rewind')).toBe('SeasonRewind')
  })
})

describe('renderTypes', () => {
  const text = renderTypes(fixture)

  it('maps every table dtype and marks nullable columns', () => {
    expect(text).toContain('export interface PlayerOverallRow {')
    expect(text).toContain('  attributed_player: string\n')
    expect(text).toContain('  player_id: number\n')
    expect(text).toContain('  neg_rate: number\n')
    expect(text).toContain('  qualified: boolean\n')
    expect(text).toContain('  birth_date: string | null\n')
    expect(text).toContain('  week: string\n')
    expect(text).toContain('  aliases: string[]\n')
  })

  it('emits the table name union and the Tables map', () => {
    expect(text).toContain('export type TableName = "player_overall" | "teams"')
    expect(text).toContain('export interface Tables {\n  player_overall: PlayerOverallRow[]\n  teams: TeamsRow[]\n}')
  })

  it('renders manifest maps, named types and nullable fields', () => {
    expect(text).toContain('  snapshots: Record<string, string | null>\n')
    expect(text).toContain('  tables: Record<string, TableEntry>\n')
    expect(text).toContain('  rules: Rules\n')
    expect(text).toContain('  share: number | null\n')
    expect(text).toContain('  live: boolean\n')
  })

  it('renders json as unknown, a value the page takes as it comes', () => {
    const withJson: ContractSchema = {
      ...fixture,
      manifest: {
        root: 'Manifest',
        types: {
          Manifest: {
            settings: { type: 'map', nullable: true, values: { type: 'json', nullable: false } },
            blob: { type: 'json', nullable: false },
          },
        },
      },
    }
    const rendered = renderTypes(withJson)
    expect(rendered).toContain('  settings: Record<string, unknown> | null\n')
    expect(rendered).toContain('  blob: unknown\n')
  })

  it('is deterministic and names the schema version in its header', () => {
    expect(renderTypes(fixture)).toBe(text)
    expect(text.startsWith('// GENERATED from src/data/schema.json (schema_version 5)')).toBe(true)
  })

  it('refuses an unknown dtype, naming the column', () => {
    const bad: ContractSchema = {
      ...fixture,
      tables: { odd: { columns: [{ name: 'x', dtype: 'decimal', nullable: false }] } },
    }
    expect(() => renderTypes(bad)).toThrow('odd.x: unknown dtype "decimal"')
  })

  it('refuses a manifest field of an undeclared type', () => {
    const bad: ContractSchema = {
      ...fixture,
      manifest: { root: 'Manifest', types: { Manifest: { rules: { type: 'Rules', nullable: false } } } },
    }
    expect(() => renderTypes(bad)).toThrow('Manifest.rules: unknown type "Rules"')
  })

  it('emits nothing for the documents block when it is empty', () => {
    expect(text).not.toContain('Columnar')
    expect(text).not.toContain('Document {')
  })
})

describe('renderTypes with a document', () => {
  const text = renderTypes(withRecap)

  it('renders the header types once, shared with the manifest', () => {
    expect(text.match(/export interface ClassifierIdentity \{/g)).toHaveLength(1)
    expect(text).toContain('export interface RecapHeader {\n  schema_version: number\n  classifiers: Record<string, ClassifierIdentity>\n}')
  })

  it('renders one row interface per frame with the table dtype map', () => {
    expect(text).toContain("/** One row of the recap document's periods frame. */\nexport interface RecapPeriodsRow {\n  period: number\n}")
    expect(text).toContain('export interface RecapPlaysRow {\n  clock: string\n  made: boolean | null\n}')
  })

  it('renders the Columnar helper once and the document, rows and frame-name shapes', () => {
    expect(text.match(/export type Columnar<T>/g)).toHaveLength(1)
    expect(text).toContain('export type RecapFrameName = "periods" | "plays"')
    expect(text).toContain('export interface RecapDocument {\n  header: RecapHeader\n  frames: {\n    periods: Columnar<RecapPeriodsRow>\n    plays: Columnar<RecapPlaysRow>\n  }\n}')
    expect(text).toContain('export interface RecapRows {\n  periods: RecapPeriodsRow[]\n  plays: RecapPlaysRow[]\n}')
  })

  it('refuses a shared type name with a different shape, naming both sides', () => {
    const bad: ContractSchema = {
      ...withRecap,
      documents: {
        recap: {
          ...withRecap.documents.recap!,
          header: {
            root: 'RecapHeader',
            types: {
              RecapHeader: { schema_version: { type: 'int', nullable: false } },
              ClassifierIdentity: { model: { type: 'string', nullable: false } },
            },
          },
        },
      },
    }
    expect(() => renderTypes(bad)).toThrow('documents.recap.header: ClassifierIdentity differs from manifest.ClassifierIdentity')
  })

  it('refuses a header root that is not declared and a frame dtype it does not know', () => {
    const noRoot: ContractSchema = {
      ...withRecap,
      documents: { recap: { ...withRecap.documents.recap!, header: { root: 'Missing', types: {} } } },
    }
    expect(() => renderTypes(noRoot)).toThrow('documents.recap.header: root Missing is not a declared type')
    const badDtype: ContractSchema = {
      ...withRecap,
      documents: { recap: { ...withRecap.documents.recap!, frames: { odd: { columns: [{ name: 'x', dtype: 'decimal', nullable: false }] } } } },
    }
    expect(() => renderTypes(badDtype)).toThrow('recap.odd.x: unknown dtype "decimal"')
  })
})
