// The board: one island. Hero sentence, lens tabs, threshold control, the
// "Read this first" note, the rows and the copy link share one view state,
// bound to the query string. Every rule number arrives as a prop.
import { useCallback, useLayoutEffect, useMemo, useState } from 'react'

import '../styles/leaderboard.css'
import { annotate, heroParts } from '../lib/annotate'
import { fmtInt } from '../lib/format'
import { rankBy, rankDeltas } from '../lib/metrics'
import { thresholdStops } from '../lib/threshold'
import type { Counts } from '../lib/types'
import { useViewState } from '../lib/url'
import { BoardRow } from './BoardRow'
import { LensTabs } from './LensTabs'
import { MethodNote } from './MethodNote'
import { SentimentBar } from './SentimentBar'
import { ThresholdControl } from './ThresholdControl'

export interface BoardPlayer extends Counts {
  name: string
  slug: string
  abbr: string | null
  headshot: string
}

export interface LeaderboardProps {
  players: BoardPlayer[]
  /** rules.qualified_threshold */
  official: number
  /** The slider's floor: rules.floors.fanbase_min_n */
  floor: number
  season: string
  /** The one corpus figure on the page: manifest.corpus[HEADLINE_POPULATION] and the player count. */
  headline: { count: number; players: number }
}

// How many rows show before "Show all": a page choice, not a rule.
const TOP = 25

export function Leaderboard({ players, official, floor, season, headline }: LeaderboardProps) {
  const defaults = useMemo(() => ({ threshold: official }), [official])
  const [view, update, ready] = useViewState(defaults)
  const { lens, n, all } = view

  // A deep link's prerendered default stays hidden until the URL is in.
  useLayoutEffect(() => {
    if (ready) document.documentElement.classList.remove('has-view')
  }, [ready])

  const stops = useMemo(() => thresholdStops(floor, Math.max(...players.map((p) => p.total)), official), [players, floor, official])
  const ranked = useMemo(() => rankBy(players, lens, n), [players, lens, n])
  const officialView = useMemo(() => rankBy(players, lens, official), [players, lens, official])
  const deltas = useMemo(() => (n === official ? null : rankDeltas(ranked, officialView, (p) => p.slug)), [ranked, officialView, n, official])
  const rankedRows = ranked.filter((r) => r.rank !== null)
  const ghostRows = ranked.filter((r) => r.rank === null)
  const shown = all ? [...rankedRows, ...ghostRows] : rankedRows.slice(0, TOP)
  const maxTotal = rankedRows.reduce((m, r) => Math.max(m, r.row.total), 0)
  const input = { ranked, lens, threshold: n, official }
  const hero = heroParts(input)
  const leader = hero.leader
  const notes = annotate(input)

  const [copied, setCopied] = useState(false)
  const copy = useCallback(() => {
    navigator.clipboard.writeText(window.location.href).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    })
  }, [])

  return (
    <section className="lb" aria-label="Leaderboard">
      <header className="lb__hero">
        <p className="lb__sentence">
          {hero.before}
          {leader && <a href={`/player/${leader.row.slug}/`}>{leader.row.name}</a>}
          {hero.after}
        </p>
        {leader && <SentimentBar counts={leader.row} size="hero" subject={leader.row.name} />}
        <p className="lb__meta mono">
          {leader && (
            <span>
              n={fmtInt(leader.row.total)} comments about {leader.row.name}
            </span>
          )}
          <span className="lb__headline">
            {fmtInt(headline.count)} comments about {headline.players} players · {season}
          </span>
        </p>
      </header>

      <LensTabs lens={lens} onChange={(l) => update({ lens: l })} />

      <ThresholdControl
        value={n}
        official={official}
        stops={stops}
        ranked={rankedRows.length}
        total={players.length}
        onChange={(v) => update({ n: v }, { replace: true })}
      />

      <MethodNote kind="read-first">
        {notes.map((s) => (
          <p key={s}>{s}</p>
        ))}
      </MethodNote>

      <ol id="lens-panel" className="lb__rows" role="tabpanel" aria-labelledby={`lens-tab-${lens}`}>
        {shown.map((r) => (
          <BoardRow
            key={r.row.slug}
            rank={r.rank}
            official={r.row.total >= official}
            name={r.row.name}
            slug={r.row.slug}
            abbr={r.row.abbr}
            headshot={r.row.headshot}
            counts={r.row}
            lens={lens}
            scale={maxTotal ? r.row.total / maxTotal : 1}
            delta={deltas?.get(r.row.slug) ?? null}
          />
        ))}
      </ol>

      <div className="lb__foot">
        <button type="button" className="lb__btn" onClick={() => update({ all: !all })}>
          {all ? `Top ${TOP}` : `Show all ${players.length}`}
        </button>
        <button type="button" className="lb__btn" onClick={copy}>
          Copy link
        </button>
        <span className="lb__copied" role="status" aria-live="polite">
          {copied ? 'Link copied' : ''}
        </span>
      </div>
    </section>
  )
}
