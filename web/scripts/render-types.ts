// Render schema.json as TypeScript. Pure: same document in, same text
// out, so the committed types.gen.ts can be diffed against a re-render.
import type { ColumnSpec, ContractSchema, FieldSpec } from '../src/data/contract'

// Parquet-side dtype vocabulary → TS. INT64 becomes number at the loader,
// date and datetime become strings there too.
const TABLE_DTYPES: Record<string, string> = {
  string: 'string',
  int64: 'number',
  float64: 'number',
  bool: 'boolean',
  date: 'string',
  datetime: 'string',
  'list<string>': 'string[]',
}

// JSON-side primitives of the manifest; json is an opaque value the
// contract declares no shape for; anything else names a type.
const MANIFEST_PRIMITIVES: Record<string, string> = {
  string: 'string',
  int: 'number',
  float: 'number',
  bool: 'boolean',
  json: 'unknown',
}

function pascal(name: string): string {
  return name
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('')
}

export function rowTypeName(table: string): string {
  return pascal(table).concat('Row')
}

/** "recap" → "Recap": the prefix of a document's generated types. */
export function documentTypeName(doc: string): string {
  return pascal(doc)
}

function columnType(table: string, col: ColumnSpec): string {
  const ts = TABLE_DTYPES[col.dtype]
  if (!ts) throw new Error(`${table}.${col.name}: unknown dtype ${JSON.stringify(col.dtype)}`)
  return col.nullable ? `${ts} | null` : ts
}

function fieldType(owner: string, field: string, spec: FieldSpec, known: Set<string>): string {
  let ts: string
  if (spec.type === 'map') {
    if (!spec.values) throw new Error(`${owner}.${field}: map without values`)
    ts = `Record<string, ${fieldType(owner, `${field}[]`, spec.values, known)}>`
  } else if (spec.type in MANIFEST_PRIMITIVES) {
    ts = MANIFEST_PRIMITIVES[spec.type] as string
  } else if (known.has(spec.type)) {
    ts = spec.type
  } else {
    throw new Error(`${owner}.${field}: unknown type ${JSON.stringify(spec.type)}`)
  }
  return spec.nullable ? `${ts} | null` : ts
}

function interfaceText(name: string, fields: Record<string, FieldSpec>, known: Set<string>): string {
  const lines = [`export interface ${name} {`]
  for (const [field, spec] of Object.entries(fields)) lines.push(`  ${field}: ${fieldType(name, field, spec, known)}`)
  lines.push('}')
  return lines.join('\n')
}

function rowsText(owner: string, name: string, doc: string, columns: readonly ColumnSpec[]): string[] {
  const lines = [`/** ${doc} */`, `export interface ${name} {`]
  for (const col of columns) lines.push(`  ${col.name}: ${columnType(owner, col)}`)
  lines.push('}', '')
  return lines
}

export function renderTypes(schema: ContractSchema): string {
  const out: string[] = []
  out.push(
    `// GENERATED from src/data/schema.json (schema_version ${schema.schema_version}) by scripts/codegen.ts.`,
    '// Do not edit: run `npm run codegen`. The build fails when this file is stale.',
    '',
  )

  const tables = Object.keys(schema.tables)
  for (const table of tables) {
    const spec = schema.tables[table]
    if (!spec) continue
    out.push(...rowsText(table, rowTypeName(table), `One row of ${table}.parquet.`, spec.columns))
  }
  out.push(`export type TableName = ${tables.map((t) => JSON.stringify(t)).join(' | ')}`, '')
  out.push('export interface Tables {')
  for (const table of tables) out.push(`  ${table}: ${rowTypeName(table)}[]`)
  out.push('}', '')

  // A JSON-side type is emitted once, however many roots declare it: the
  // manifest and a document header may both carry ClassifierIdentity. The
  // same name with a different shape is a contract error, not a second type.
  const emitted = new Map<string, { text: string; owner: string }>()
  const emit = (owner: string, name: string, fields: Record<string, FieldSpec>, known: Set<string>) => {
    const text = interfaceText(name, fields, known)
    const prior = emitted.get(name)
    if (!prior) {
      emitted.set(name, { text, owner })
      out.push(text, '')
    } else if (prior.text !== text) {
      throw new Error(`${owner}: ${name} differs from ${prior.owner}.${name}`)
    }
  }

  const manifestTypes = new Set(Object.keys(schema.manifest.types))
  if (!manifestTypes.has(schema.manifest.root)) throw new Error(`manifest root ${schema.manifest.root} is not a declared type`)
  for (const [name, fields] of Object.entries(schema.manifest.types)) emit('manifest', name, fields, manifestTypes)

  const documents = Object.entries(schema.documents)
  if (documents.length) out.push('/** A frame as a document carries it: one array per column. */', 'export type Columnar<T> = { [K in keyof T]: T[K][] }', '')
  for (const [doc, spec] of documents) {
    const owner = `documents.${doc}.header`
    const known = new Set([...manifestTypes, ...Object.keys(spec.header.types)])
    if (!(spec.header.root in spec.header.types)) throw new Error(`${owner}: root ${spec.header.root} is not a declared type`)
    for (const [name, fields] of Object.entries(spec.header.types)) emit(owner, name, fields, known)

    const prefix = documentTypeName(doc)
    const frames = Object.keys(spec.frames)
    const rowName = (frame: string) => rowTypeName(`${doc}_${frame}`)
    for (const frame of frames) {
      const columns = spec.frames[frame]?.columns ?? []
      out.push(...rowsText(`${doc}.${frame}`, rowName(frame), `One row of the ${doc} document's ${frame} frame.`, columns))
    }
    out.push(`export type ${prefix}FrameName = ${frames.map((f) => JSON.stringify(f)).join(' | ')}`, '')
    out.push(`/** The ${doc} document as published: its header and its frames as column arrays. */`, `export interface ${prefix}Document {`, `  header: ${spec.header.root}`, '  frames: {')
    for (const frame of frames) out.push(`    ${frame}: Columnar<${rowName(frame)}>`)
    out.push('  }', '}', '')
    out.push(`/** The ${doc} document's frames as rows. */`, `export interface ${prefix}Rows {`)
    for (const frame of frames) out.push(`  ${frame}: ${rowName(frame)}[]`)
    out.push('}', '')
  }
  return out.join('\n')
}
