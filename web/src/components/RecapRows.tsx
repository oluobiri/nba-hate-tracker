// The recaps list: one curated recap per row in config order, the whole
// row the link. Face, name, the game line, the hook, the period strip, n.
// On a phone the strip drops to a second line, as n does on the board.
import { fmtInt } from '../lib/format'
import { headshotSrcSet } from '../lib/media'
import { recapHref, type Recap } from '../lib/recaps'
import { GameLine } from './GameLine'
import { PeriodStrip } from './PeriodStrip'

export interface RecapRowsProps {
  recaps: readonly Recap[]
}

export function RecapRows({ recaps }: RecapRowsProps) {
  return (
    <ol className="rr">
      {recaps.map((r) => {
        const name = r.entry.attributed_player
        const headshot = r.player.headshot_url
        return (
          <li key={r.key} className="rr__row">
            <a className="rr__link" href={recapHref(r.key)}>
              <img className="rr__mug" src={headshot} srcSet={headshotSrcSet(headshot)} sizes="44px" width="44" height="44" alt="" loading="lazy" decoding="async" />
              <span className="rr__who">
                <span className="rr__game mono">
                  <GameLine parts={r.line} />
                </span>
                <span className="rr__name">{name}</span>
                <span className="rr__hook">{r.hook}</span>
              </span>
              <span className="rr__strip">
                <PeriodStrip cells={r.cells} subject={name} />
              </span>
              <span className="rr__n mono">
                {fmtInt(r.entry.live_n)}
                <span className="rr__n-unit"> n</span>
              </span>
              <span className="rr__chevron" aria-hidden="true">
                ›
              </span>
            </a>
          </li>
        )
      })}
    </ol>
  )
}
