// Refresh the contract snapshot from DATA_BASE and render src/data/types.gen.ts
// from it. `--check` re-renders from the committed snapshot alone (offline)
// and exits 1 when the committed types differ, which is how a stale file
// fails `npm run build`.
import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import type { ContractSchema } from '../src/data/contract'
import { readJson, resolveDataBase, seasonLocation } from '../src/data/env'
import { CURRENT_SEASON } from '../src/site'
import { renderTypes } from './render-types'

const here = path.dirname(fileURLToPath(import.meta.url))
const SNAPSHOT = path.resolve(here, '../src/data/schema.json')
const TYPES = path.resolve(here, '../src/data/types.gen.ts')

async function readSnapshot(): Promise<ContractSchema> {
  return JSON.parse(await readFile(SNAPSHOT, 'utf8')) as ContractSchema
}

async function check(): Promise<void> {
  const expected = renderTypes(await readSnapshot())
  const actual = await readFile(TYPES, 'utf8').catch(() => null)
  if (actual === expected) {
    console.log(`codegen: ${path.relative(process.cwd(), TYPES)} is current`)
    return
  }
  console.error(
    actual === null
      ? `codegen: ${TYPES} is missing; run npm run codegen`
      : `codegen: ${TYPES} is stale against src/data/schema.json; run npm run codegen`,
  )
  process.exit(1)
}

async function refresh(): Promise<void> {
  const base = resolveDataBase()
  const loc = seasonLocation(CURRENT_SEASON, base)
  const schema = await readJson<ContractSchema>(loc, 'schema.json')
  await writeFile(SNAPSHOT, `${JSON.stringify(schema, null, 2)}\n`)
  await writeFile(TYPES, renderTypes(schema))
  const tables = Object.keys(schema.tables).length
  console.log(`codegen: schema_version ${schema.schema_version}, ${tables} tables from ${base}`)
  console.log(`codegen: wrote ${path.relative(process.cwd(), SNAPSHOT)} and ${path.relative(process.cwd(), TYPES)}`)
}

if (process.argv.includes('--check')) await check()
else await refresh()
