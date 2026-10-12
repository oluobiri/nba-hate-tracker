// The loudest game threads: one numbered list. Each row is the score with
// the winner bold, the stage and date, a Recap chip where one exists, the
// volume bar on a scale shared across both lists, the split, and one
// computed sentence on who the thread was about.
import { fmtInt } from '../lib/format'
import { recapHref } from '../lib/recaps'
import { type Thread, threadFigure } from '../lib/season'
import { RecapChip } from './RecapChip'
import { SentimentBar } from './SentimentBar'

export interface ThreadListProps {
  /** "In the playoffs" / "Regular season". */
  title: string
  threads: readonly Thread[]
  /** The most comments about players in any thread of either list: the full bar. */
  max: number
}

const playerHref = (slug: string): string => `/player/${slug}/`
const surname = (name: string): string => name.split(' ').at(-1)!

export function ThreadList({ title, threads, max }: ThreadListProps) {
  return (
    <div className="lt">
      <h3>{title}</h3>
      <ol className="lt__list">
        {threads.map((t, i) => (
          <li key={t.gameId} className="lt__row">
            <span className="lt__rank">{i + 1}</span>
            <div className="lt__game">
              <span className="lt__score">
                {t.line.away.won ? <b>{`${t.line.away.abbr} ${t.line.away.score}`}</b> : `${t.line.away.abbr} ${t.line.away.score}`} @{' '}
                {t.line.home.won ? <b>{`${t.line.home.abbr} ${t.line.home.score}`}</b> : `${t.line.home.abbr} ${t.line.home.score}`}
              </span>
              <span className="lt__when mono">
                {t.stage} · {t.line.date}
              </span>
              {t.recaps.map((r) => (
                <RecapChip key={r.key} href={recapHref(r.key)} label={t.recaps.length > 1 ? `Recap · ${surname(r.name)}` : 'Recap'} />
              ))}
            </div>
            <div className="lt__vol">
              <i style={{ width: `${max ? (t.counts.total / max) * 100 : 0}%` }} />
              <span className="mono">
                {fmtInt(t.counts.total)} <small>about players{t.reddit !== null && `, of ${fmtInt(t.reddit)} in the thread`}</small>
              </span>
            </div>
            <SentimentBar counts={t.counts} size="row" subject={`${t.line.away.abbr} at ${t.line.home.abbr}, ${t.line.date}`} />
            <p className="lt__who">
              Mostly about <a href={playerHref(t.top.slug)}>{t.top.name}</a>, {threadFigure(t.top)}.
              {t.second && (
                <>
                  {' '}
                  <a href={playerHref(t.second.slug)}>{t.second.name}</a> {threadFigure(t.second)}.
                </>
              )}
            </p>
          </li>
        ))}
      </ol>
    </div>
  )
}
