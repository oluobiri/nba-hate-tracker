import { describe, expect, it } from 'vitest'

import type { ContractSchema } from '../src/data/contract'
import { renderTypes, rowTypeName } from './render-types'

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
}

describe('rowTypeName', () => {
  it('pascal-cases the table name and appends Row', () => {
    expect(rowTypeName('player_fan_team')).toBe('PlayerFanTeamRow')
    expect(rowTypeName('teams')).toBe('TeamsRow')
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
})
