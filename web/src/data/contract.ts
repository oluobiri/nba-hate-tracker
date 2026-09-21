// The committed contract snapshot, typed. schema.json is refreshed by
// `npm run codegen`; SCHEMA_VERSION and every table's column list are read
// from it here, so the generated file carries types only.
import snapshot from './schema.json'
import type { TableName } from './types.gen'

export interface ColumnSpec {
  name: string
  dtype: string
  nullable: boolean
}

export interface FieldSpec {
  type: string
  nullable: boolean
  values?: FieldSpec
}

export interface ContractSchema {
  schema_version: number
  tables: Record<string, { columns: ColumnSpec[] }>
  manifest: { root: string; types: Record<string, Record<string, FieldSpec>> }
}

export const CONTRACT: ContractSchema = snapshot as ContractSchema
export const SCHEMA_VERSION: number = CONTRACT.schema_version
export const TABLE_NAMES: readonly TableName[] = Object.keys(CONTRACT.tables) as TableName[]

export function columnsOf(table: string): ColumnSpec[] {
  const spec = CONTRACT.tables[table]
  if (!spec) throw new Error(`${table}: not a contract table`)
  return spec.columns
}

export class ContractError extends Error {
  override name = 'ContractError'
}
