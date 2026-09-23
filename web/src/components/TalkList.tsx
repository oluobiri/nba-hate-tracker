// Who they talk about: this fanbase's most-discussed players, own roster
// included. The bar's length is his share of the list's leader, its
// segments the split; n is printed. Own-roster rows carry a tag.
import type { TalkRow } from '../lib/fanbase'
import { fmtInt } from '../lib/format'
import { headshotSrcSet } from '../lib/media'
import { SentimentBar } from './SentimentBar'

export interface TalkListProps {
  /** Already ranked by the caller. */
  rows: readonly TalkRow[]
  /** Whose comments these are, for the bars' text alternatives. */
  fans: string
}

export function TalkList({ rows, fans }: TalkListProps) {
  const max = rows[0]?.total ?? 1
  return (
    <ol className="tk">
      {rows.map((r, i) => (
        <li key={r.slug} className={`tk__row${r.own ? ' tk__row--own' : ''}`}>
          <a className="tk__link" href={`/player/${r.slug}/`}>
            <span className="tk__rank mono">{i + 1}</span>
            <img className="tk__mug" src={r.headshot} srcSet={headshotSrcSet(r.headshot)} sizes="44px" width="44" height="44" alt="" loading="lazy" decoding="async" />
            <span className="tk__who">
              <span className="tk__name">{r.name}</span>
              <span className="tk__team mono">
                {r.abbr ?? 'FA'}
                {r.own && <span className="tk__tag">own roster</span>}
              </span>
            </span>
            <span className="tk__bar">
              <SentimentBar counts={r} size="row" length="relative" scale={r.total / max} subject={`${fans} on ${r.name}`} />
            </span>
            <span className="tk__n mono">
              {fmtInt(r.total)}
              <span className="tk__n-unit"> n</span>
            </span>
          </a>
        </li>
      ))}
    </ol>
  )
}
