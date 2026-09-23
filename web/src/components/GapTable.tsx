// Their own players: one row per tracked roster player, own fans' negative
// rate against every other fanbase summed, the gap in points. Tint follows
// direction, ice where own fans are kinder and heat where harsher, and the
// sign is printed; a row under the floor keeps its rates in gray and no Δ.
import type { CSSProperties } from 'react'

import type { GapRow } from '../lib/fanbase'
import { fmtInt, fmtPct, fmtSigned } from '../lib/format'
import { headshotSrcSet } from '../lib/media'
import { negRate } from '../lib/metrics'

export interface GapTableProps {
  rows: readonly GapRow[]
  /** The visually hidden caption: whose players these are. */
  caption: string
  /** Own-fans comments a row needs for a Δ, from the manifest. */
  floor: number
}

// The tint saturates at this gap, so a 20-point and a 40-point gap read the same.
const FULL_TINT = 0.2
const MAX_MIX = 40

type Direction = 'kinder' | 'harsher' | 'even' | 'thin'

const direction = (delta: number | null): Direction => (delta === null ? 'thin' : delta < 0 ? 'kinder' : delta > 0 ? 'harsher' : 'even')

export function GapTable({ rows, caption, floor }: GapTableProps) {
  return (
    <table className="gap">
      <caption className="visually-hidden">{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Player</th>
          <th scope="col">Own fans</th>
          <th scope="col">Rival fans</th>
          <th scope="col">
            <abbr title="Own fans' negative rate minus rival fans', in points">Δ</abbr>
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const dir = direction(r.delta)
          const mix = r.delta === null ? 0 : (Math.min(Math.abs(r.delta), FULL_TINT) / FULL_TINT) * MAX_MIX
          const said =
            r.delta === null
              ? `under the floor of ${fmtInt(floor)} of their own comments, so no gap is read`
              : dir === 'even'
                ? 'no different from rival fans'
                : `${(100 * Math.abs(r.delta)).toFixed(0)} points ${dir} than rival fans`
          return (
            <tr key={r.slug} className={`gap__row gap__row--${dir}`} style={{ '--gap-mix': `${mix}%` } as CSSProperties}>
              <th scope="row" className="gap__player">
                <a className="gap__link" href={`/player/${r.slug}/`}>
                  <img className="gap__mug" src={r.headshot} srcSet={headshotSrcSet(r.headshot)} sizes="44px" width="44" height="44" alt="" loading="lazy" decoding="async" />
                  <span className="gap__name">{r.name}</span>
                  {r.position && <span className="gap__pos mono">{r.position}</span>}
                </a>
              </th>
              <td className="gap__rate mono">
                {fmtPct(negRate(r.own), 0)}
                <span className="gap__n">n={fmtInt(r.own.total)}</span>
              </td>
              <td className="gap__rate mono">{fmtPct(negRate(r.rivals), 0)}</td>
              <td className="gap__delta mono">
                {r.delta === null ? <span aria-hidden="true">—</span> : fmtSigned(r.delta, 0)}
                <span className="visually-hidden"> {said}</span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
