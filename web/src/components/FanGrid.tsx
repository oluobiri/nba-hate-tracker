// The full grid: thirty fanbases on thirty rosters as one table. A cell is
// the fanbase's negative rate on that roster, tinted by its distance from
// the roster's usual (heat harsher, ice kinder) or, toggled, by the raw
// share. Desktop only: the stylesheet hides the island under 1024 px, so
// a phone never hydrates it. One sentence per cell serves the tooltip, the
// cell's spoken text and the page's worked example alike.
import { type CSSProperties, type FocusEvent, type KeyboardEvent, memo, type MouseEvent, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { possessive } from '../lib/fans'
import { fmtInt, fmtPct, fmtSigned } from '../lib/format'
import { cellSentence, type GridCell, type GridTeam, minPresets, moveFocus, rampMix, tipSide } from '../lib/league'
import { type Scale, useViewState } from '../lib/url'

import '../styles/fangrid.css'

export interface GridPos {
  row: number
  col: number
}

export interface FanGridProps {
  teams: readonly GridTeam[]
  cells: readonly GridCell[]
  /** The Δ that fills a cell, a fraction: the farthest either headline list reaches from zero. */
  limit: number
  /** The published cell floor: the presets' unit and the default minimum. */
  floor: number
  /** The official threshold, which every view state carries; the grid never reads it. */
  official: number
  /** The table's text alternative, computed at build. */
  caption: string
  /** The worked example's cell, which also takes the first tab stop. */
  example: GridPos
  /** Style guide only: a forced scale, and a cell whose tip is drawn open. */
  demo?: { scale: Scale; open?: GridPos }
}

const SCALES: { key: Scale; label: string }[] = [
  { key: 'delta', label: "Δ vs each roster's usual" },
  { key: 'raw', label: 'Negative share' },
]

const EMPTY = { n: 0, neg: 0, usual: 0 }

const posOf = (e: Element | null): GridPos | null => {
  const td = e?.closest<HTMLElement>('td[data-r]')
  return td ? { row: Number(td.dataset.r), col: Number(td.dataset.c) } : null
}
const same = (a: GridPos | null, b: GridPos | null): boolean => a?.row === b?.row && a?.col === b?.col

export function FanGrid({ teams, cells, limit, floor, official, caption, example, demo }: FanGridProps) {
  const defaults = useMemo(() => ({ threshold: official, min: floor }), [official, floor])
  const [view, update, ready] = useViewState(defaults)
  const scale = demo?.scale ?? view.scale
  const min = demo ? floor : Math.max(floor, view.min)
  const presets = useMemo(() => minPresets(floor), [floor])
  const n = teams.length
  // Cells by row then column; a pair with no comments is an empty cell.
  const rows = useMemo(() => {
    const grid: GridCell[][] = teams.map((_, r) => teams.map((__, c) => ({ f: r, r: c, ...EMPTY })))
    for (const x of cells) grid[x.f]![x.r] = x
    return grid
  }, [teams, cells])
  const [active, setActive] = useState<GridPos | null>(null)
  const [stop, setStop] = useState<GridPos>(example)
  const body = useRef<HTMLTableSectionElement>(null)

  useLayoutEffect(() => {
    if (ready) document.documentElement.classList.remove('has-grid-view')
  }, [ready])

  const onKeyDown = (e: KeyboardEvent<HTMLTableSectionElement>): void => {
    const from = posOf(e.target as Element)
    if (!from) return
    const next = moveFocus(from.row, from.col, e.key, n)
    if (!next) return
    e.preventDefault()
    setStop({ row: next.r, col: next.c })
    body.current?.rows[next.r]?.cells[next.c + 1]?.focus()
  }
  const point = (e: MouseEvent<HTMLTableSectionElement> | FocusEvent<HTMLTableSectionElement>): void => {
    const p = posOf(e.target as Element)
    setActive((prev) => (same(prev, p) ? prev : p))
  }
  const clear = (): void => setActive(null)

  return (
    <div className="fg">
      <div className="fg__controls">
        <div className="fg__group" role="group" aria-label="Colour by">
          {SCALES.map((s) => (
            <button key={s.key} type="button" className="btn" aria-pressed={s.key === scale} onClick={() => update({ scale: s.key })}>
              {s.label}
            </button>
          ))}
        </div>
        <div className="fg__group" role="group" aria-label="Minimum comments per cell">
          <span className="fg__label mono">min. comments per cell</span>
          {presets.map((p) => (
            <button key={p} type="button" className="btn" aria-pressed={p === min} onClick={() => update({ min: p })}>
              {fmtInt(p)}
            </button>
          ))}
        </div>
      </div>
      <p className="fg__axis mono" aria-hidden="true">
        talking about players on →
      </p>
      <table className="fg__table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col" className="fg__corner mono">
              <span aria-hidden="true">Fans of ↓</span>
              <span className="visually-hidden">Fans of</span>
            </th>
            {teams.map((t, c) => (
              <th key={t.abbr} scope="col" className={`fg__ch mono${active?.col === c ? ' fg__ch--x' : ''}`}>
                <span aria-hidden="true">{t.abbr}</span>
                <span className="visually-hidden">{t.team} players</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody ref={body} onKeyDown={onKeyDown} onMouseOver={point} onMouseLeave={clear} onFocus={point} onBlur={clear}>
          {teams.map((t, r) => (
            <Row
              key={t.abbr}
              r={r}
              team={t}
              cells={rows[r]!}
              teams={teams}
              n={n}
              scale={scale}
              min={min}
              limit={limit}
              hlCol={active?.col ?? -1}
              hlRow={active?.row === r}
              stopCol={stop.row === r ? stop.col : -1}
              egCol={example.row === r ? example.col : -1}
              openCol={demo?.open?.row === r ? demo.open.col : -1}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface RowProps {
  r: number
  team: GridTeam
  cells: readonly GridCell[]
  teams: readonly GridTeam[]
  n: number
  scale: Scale
  min: number
  limit: number
  hlCol: number
  hlRow: boolean
  stopCol: number
  egCol: number
  openCol: number
}

// One row; memoised so a crosshair move re-renders rows, not the page.
const Row = memo(function Row({ r, team, cells, teams, n, scale, min, limit, hlCol, hlRow, stopCol, egCol, openCol }: RowProps) {
  return (
    <tr className={hlRow ? 'fg__row--x' : undefined}>
      <th scope="row" className="fg__rh mono">
        {possessive(team.team)}
      </th>
      {cells.map((cell, c) => {
        const text = cellSentence(cell, teams, min)
        if (c === r) {
          return (
            <td key={c} className="fg__cell fg__cell--diag">
              <span className="visually-hidden">{text}</span>
            </td>
          )
        }
        const under = cell.n < min
        const rate = cell.n ? cell.neg / cell.n : 0
        const dneg = cell.n ? rate - cell.usual : 0
        const t = scale === 'delta' ? (limit > 0 ? Math.abs(dneg) / limit : 0) : rate
        const tone = scale === 'delta' && dneg < 0 ? 'ice' : 'heat'
        const { mix, bright } = under ? { mix: 0, bright: false } : rampMix(t, tone)
        const figure = under ? '–' : scale === 'delta' ? fmtSigned(dneg, 0) : fmtPct(rate, 0)
        const cls = [
          'fg__cell',
          `fg__cell--${tone}`,
          `fg__cell--tip-${tipSide(c, n)}`,
          under && 'fg__cell--under',
          bright && 'fg__cell--bright',
          hlCol === c && 'fg__cell--x',
          egCol === c && 'fg__cell--eg',
          openCol === c && 'fg__cell--open',
        ]
          .filter(Boolean)
          .join(' ')
        return (
          <td key={c} className={cls} data-r={r} data-c={c} tabIndex={stopCol === c ? 0 : -1} style={{ '--fg-mix': `${mix}%` } as CSSProperties}>
            <span aria-hidden="true">{figure}</span>
            <span className="visually-hidden">{text}</span>
            <span className="fg__tip" aria-hidden="true">
              {text}
            </span>
          </td>
        )
      })}
    </tr>
  )
})
