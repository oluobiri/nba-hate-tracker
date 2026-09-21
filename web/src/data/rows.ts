// Parquet values → the contract's JS shapes, once, at the loader boundary.
// INT64 → number; DATE → "YYYY-MM-DD"; naive TIMESTAMP → "YYYY-MM-DDTHH:MM:SS";
// a null in a non-nullable column is a contract failure naming the row.
import { type ColumnSpec, ContractError } from './contract'

export type RawRow = Record<string, unknown>

// Flat parquet schema element, as hyparquet's metadata lists them.
export interface SchemaElement {
  name: string
  type?: string
  converted_type?: string
  logical_type?: { type: string }
  num_children?: number
}

/** The contract dtype a top-level parquet column carries, or null if it is outside the vocabulary. */
export function parquetDtype(el: SchemaElement, leaf?: SchemaElement): string | null {
  const logical = el.logical_type?.type
  if (el.num_children) {
    if ((logical === 'LIST' || el.converted_type === 'LIST') && leaf && parquetDtype(leaf) === 'string') return 'list<string>'
    return null
  }
  switch (el.type) {
    case 'BYTE_ARRAY':
      return logical === 'STRING' || el.converted_type === 'UTF8' ? 'string' : null
    case 'INT64':
      return logical === 'TIMESTAMP' ? 'datetime' : logical ? null : 'int64'
    case 'INT32':
      return logical === 'DATE' || el.converted_type === 'DATE' ? 'date' : null
    case 'DOUBLE':
      return 'float64'
    case 'BOOLEAN':
      return 'bool'
    default:
      return null
  }
}

/** Top-level columns of a flat parquet schema as (element, leaf) pairs; nested groups collapse to their first leaf. */
export function topLevelColumns(schema: readonly SchemaElement[]): { el: SchemaElement; leaf?: SchemaElement }[] {
  const out: { el: SchemaElement; leaf?: SchemaElement }[] = []
  let i = 1 // index 0 is the root group
  const skip = (start: number): number => {
    // Return the index just past the subtree rooted at `start`.
    let idx = start + 1
    for (let n = schema[start]?.num_children ?? 0; n > 0; n--) idx = skip(idx)
    return idx
  }
  while (i < schema.length) {
    const el = schema[i] as SchemaElement
    const end = skip(i)
    let leaf: SchemaElement | undefined
    if (el.num_children) {
      for (let j = i + 1; j < end; j++) {
        if (!schema[j]?.num_children) {
          leaf = schema[j]
          break
        }
      }
    }
    out.push({ el, leaf })
    i = end
  }
  return out
}

const isoDate = (d: Date): string => d.toISOString().slice(0, 10)
const isoNaive = (d: Date): string => d.toISOString().slice(0, 19)

export function normaliseRow(table: string, row: RawRow, columns: readonly ColumnSpec[], index: number): RawRow {
  const out: RawRow = {}
  for (const col of columns) {
    const v = row[col.name]
    if (v === null || v === undefined) {
      if (!col.nullable) throw new ContractError(`${table}.${col.name}: null at row ${index}, declared non-nullable`)
      out[col.name] = null
      continue
    }
    switch (col.dtype) {
      case 'int64':
        if (typeof v === 'bigint') {
          if (v > BigInt(Number.MAX_SAFE_INTEGER) || v < BigInt(Number.MIN_SAFE_INTEGER))
            throw new ContractError(`${table}.${col.name}: ${v} exceeds the safe integer range at row ${index}`)
          out[col.name] = Number(v)
        } else if (typeof v === 'number' && Number.isInteger(v)) out[col.name] = v
        else throw new ContractError(`${table}.${col.name}: expected an integer at row ${index}, got ${typeof v}`)
        break
      case 'float64':
        if (typeof v !== 'number') throw new ContractError(`${table}.${col.name}: expected a number at row ${index}, got ${typeof v}`)
        out[col.name] = v
        break
      case 'bool':
        if (typeof v !== 'boolean') throw new ContractError(`${table}.${col.name}: expected a boolean at row ${index}, got ${typeof v}`)
        out[col.name] = v
        break
      case 'string':
        if (typeof v !== 'string') throw new ContractError(`${table}.${col.name}: expected a string at row ${index}, got ${typeof v}`)
        out[col.name] = v
        break
      case 'date':
      case 'datetime':
        if (!(v instanceof Date)) throw new ContractError(`${table}.${col.name}: expected a Date at row ${index}, got ${typeof v}`)
        out[col.name] = col.dtype === 'date' ? isoDate(v) : isoNaive(v)
        break
      case 'list<string>':
        if (!Array.isArray(v) || v.some((x) => typeof x !== 'string'))
          throw new ContractError(`${table}.${col.name}: expected a list of strings at row ${index}`)
        out[col.name] = v
        break
      default:
        throw new ContractError(`${table}.${col.name}: unknown dtype ${col.dtype}`)
    }
  }
  return out
}
