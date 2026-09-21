// Render schema.json as TypeScript. Pure: same document in, same text
// out, so the committed types.gen.ts can be diffed against a re-render.

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

// JSON-side primitives of the manifest; anything else names a type.
const MANIFEST_PRIMITIVES: Record<string, string> = {
  string: 'string',
  int: 'number',
  float: 'number',
  bool: 'boolean',
}

export function rowTypeName(table: string): string {
  return table
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('')
    .concat('Row')
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
    out.push(`/** One row of ${table}.parquet. */`, `export interface ${rowTypeName(table)} {`)
    for (const col of spec.columns) out.push(`  ${col.name}: ${columnType(table, col)}`)
    out.push('}', '')
  }
  out.push(`export type TableName = ${tables.map((t) => JSON.stringify(t)).join(' | ')}`, '')
  out.push('export interface Tables {')
  for (const table of tables) out.push(`  ${table}: ${rowTypeName(table)}[]`)
  out.push('}', '')

  const known = new Set(Object.keys(schema.manifest.types))
  if (!known.has(schema.manifest.root)) throw new Error(`manifest root ${schema.manifest.root} is not a declared type`)
  for (const [name, fields] of Object.entries(schema.manifest.types)) {
    out.push(`export interface ${name} {`)
    for (const [field, spec] of Object.entries(fields)) out.push(`  ${field}: ${fieldType(name, field, spec, known)}`)
    out.push('}', '')
  }
  return out.join('\n')
}
