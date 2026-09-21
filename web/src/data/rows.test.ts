import { describe, expect, it } from 'vitest'

import type { ColumnSpec } from './contract'
import { normaliseRow, parquetDtype, type SchemaElement, topLevelColumns } from './rows'

describe('parquetDtype', () => {
  it.each<[SchemaElement, string | null]>([
    [{ name: 's', type: 'BYTE_ARRAY', converted_type: 'UTF8', logical_type: { type: 'STRING' } }, 'string'],
    [{ name: 'i', type: 'INT64' }, 'int64'],
    [{ name: 'f', type: 'DOUBLE' }, 'float64'],
    [{ name: 'b', type: 'BOOLEAN' }, 'bool'],
    [{ name: 'd', type: 'INT32', converted_type: 'DATE', logical_type: { type: 'DATE' } }, 'date'],
    [{ name: 't', type: 'INT64', logical_type: { type: 'TIMESTAMP' } }, 'datetime'],
    [{ name: 'raw', type: 'BYTE_ARRAY' }, null],
    [{ name: 'i32', type: 'INT32' }, null],
  ])('maps %o to %s', (el, expected) => {
    expect(parquetDtype(el)).toBe(expected)
  })

  it('maps a LIST group with a string leaf to list<string>', () => {
    const group: SchemaElement = { name: 'aliases', logical_type: { type: 'LIST' }, num_children: 1 }
    const leaf: SchemaElement = { name: 'element', type: 'BYTE_ARRAY', logical_type: { type: 'STRING' } }
    expect(parquetDtype(group, leaf)).toBe('list<string>')
    expect(parquetDtype(group, { name: 'element', type: 'INT64' })).toBeNull()
  })
})

describe('topLevelColumns', () => {
  it('skips the root and collapses nested groups to their first leaf', () => {
    const schema: SchemaElement[] = [
      { name: 'root', num_children: 3 },
      { name: 'a', type: 'INT64' },
      { name: 'aliases', logical_type: { type: 'LIST' }, num_children: 1 },
      { name: 'list', num_children: 1 },
      { name: 'element', type: 'BYTE_ARRAY', logical_type: { type: 'STRING' } },
      { name: 'b', type: 'BOOLEAN' },
    ]
    const cols = topLevelColumns(schema)
    expect(cols.map((c) => c.el.name)).toEqual(['a', 'aliases', 'b'])
    expect(cols[1]?.leaf?.name).toBe('element')
  })
})

describe('normaliseRow', () => {
  const columns: ColumnSpec[] = [
    { name: 'id', dtype: 'int64', nullable: false },
    { name: 'rate', dtype: 'float64', nullable: false },
    { name: 'day', dtype: 'date', nullable: true },
    { name: 'week', dtype: 'datetime', nullable: false },
    { name: 'flag', dtype: 'bool', nullable: false },
    { name: 'name', dtype: 'string', nullable: true },
  ]

  it('converts bigint, Date and null per dtype', () => {
    const out = normaliseRow('t', {
      id: 42n,
      rate: 0.5,
      day: new Date('2025-10-01T00:00:00Z'),
      week: new Date('2025-09-29T00:00:00Z'),
      flag: true,
      name: null,
    }, columns, 0)
    expect(out).toEqual({ id: 42, rate: 0.5, day: '2025-10-01', week: '2025-09-29T00:00:00', flag: true, name: null })
  })

  it('names table, column and row on a null in a non-nullable column', () => {
    expect(() => normaliseRow('players', { id: null }, [columns[0]!], 7)).toThrow('players.id: null at row 7')
  })

  it('refuses a bigint outside the safe integer range', () => {
    expect(() => normaliseRow('t', { id: 2n ** 60n }, [columns[0]!], 0)).toThrow('exceeds the safe integer range')
  })

  it('refuses a value of the wrong JS type', () => {
    expect(() => normaliseRow('t', { rate: '0.5' }, [columns[1]!], 3)).toThrow('t.rate: expected a number at row 3')
  })
})
