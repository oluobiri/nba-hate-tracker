// Load one season from the published contract at build time: the
// manifest, then exactly the files its registry names, checked against
// the committed snapshot before any page reads a row.
import { isDeepStrictEqual } from 'node:util'

import { parquetMetadata, parquetReadObjects } from 'hyparquet'
import { compressors } from 'hyparquet-compressors'

import { assertManifest, assertParquetSchema, assertTables } from './assert'
import { CONTRACT, ContractError, type ContractSchema, columnsOf } from './contract'
import { readBytes, readJson, resolveDataBase, type SeasonLocation, seasonLocation } from './env'
import { normaliseRow, type RawRow, type SchemaElement } from './rows'
import type { Manifest, TableName, Tables } from './types.gen'

export interface SeasonData {
  season: string
  source: string
  manifest: Manifest
  tables: Tables
  warnings: string[]
}

function describeDrift(remote: ContractSchema): string {
  if (remote.schema_version !== CONTRACT.schema_version)
    return `schema_version ${remote.schema_version} published, snapshot has ${CONTRACT.schema_version}`
  for (const name of new Set([...Object.keys(CONTRACT.tables), ...Object.keys(remote.tables)])) {
    if (!isDeepStrictEqual(CONTRACT.tables[name], remote.tables[name])) return `table ${name} differs`
  }
  for (const name of new Set([...Object.keys(CONTRACT.manifest.types), ...Object.keys(remote.manifest.types)])) {
    if (!isDeepStrictEqual(CONTRACT.manifest.types[name], remote.manifest.types[name])) return `manifest type ${name} differs`
  }
  return 'documents differ'
}

async function loadTable(loc: SeasonLocation, table: TableName, file: string): Promise<RawRow[]> {
  const columns = columnsOf(table)
  const bytes = await readBytes(loc, file)
  const metadata = parquetMetadata(bytes)
  assertParquetSchema(table, metadata.schema as unknown as SchemaElement[], columns)
  const raw = (await parquetReadObjects({ file: bytes, compressors })) as RawRow[]
  return raw.map((row, i) => normaliseRow(table, row, columns, i))
}

export async function loadSeason(season: string, base: string = resolveDataBase()): Promise<SeasonData> {
  const loc = seasonLocation(season, base)

  const remote = await readJson<ContractSchema>(loc, 'schema.json')
  if (!isDeepStrictEqual(remote, CONTRACT))
    throw new ContractError(`contract drift at ${loc.root}: ${describeDrift(remote)}; run npm run codegen`)

  const manifest = await readJson<Manifest>(loc, 'manifest.json')
  assertManifest(manifest, season)

  const loaded = await Promise.all(
    Object.entries(manifest.tables).map(async ([name, entry]) => [name, await loadTable(loc, name as TableName, entry.file)] as const),
  )
  const tables = Object.fromEntries(loaded) as unknown as Tables

  const warnings = assertTables(tables, manifest)
  return { season, source: loc.root, manifest, tables, warnings }
}
