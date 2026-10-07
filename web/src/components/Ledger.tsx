import type { ReactNode } from 'react'

import { fmtInt } from '../lib/format'

export interface LedgerColumn<T> {
  head: string
  cell: (row: T) => ReactNode
  /** The first column may be the row's heading. */
  rowHead?: boolean
  /** The column that holds the comment: wraps at a readable measure. */
  body?: boolean
}

export interface LedgerProps<T> {
  columns: readonly LedgerColumn<T>[]
  rows: readonly T[]
  keyOf: (row: T) => string
  /** The visually hidden caption. */
  caption: string
}

/** A table that becomes a stack of labeled blocks on a phone; each cell carries its column head. */
export function Ledger<T>({ columns, rows, keyOf, caption }: LedgerProps<T>) {
  return (
    <table className="ledger">
      <caption className="visually-hidden">{caption}</caption>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.head} scope="col">
              {c.head}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={keyOf(r)}>
            {columns.map((c) =>
              c.rowHead ? (
                <th key={c.head} scope="row">
                  {c.cell(r)}
                </th>
              ) : (
                <td key={c.head} data-l={c.head} className={c.body ? 'ledger__body' : undefined}>
                  {c.cell(r)}
                </td>
              ),
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Date, score and the permalink, as one small line under a quoted body. */
export function SourceLine({ date, score, url }: { date: string; score: number; url: string }) {
  return (
    <span className="src">
      {date} · ▲ {fmtInt(score)} ·{' '}
      <a href={url} rel="noopener noreferrer">
        Source ↗
      </a>
    </span>
  )
}

/** Names as chips: the finder's matches, the classifier's pick. */
export function Chips({ names }: { names: readonly string[] }) {
  return (
    <>
      {names.map((n) => (
        <span key={n} className="namechip">
          {n}
        </span>
      ))}
    </>
  )
}
