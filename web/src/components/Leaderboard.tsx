// The board: one island. Hero sentence, lens tabs, threshold control, the
// "Read this first" note, the rows and the copy link share one view state,
// bound to the query string. Every rule number arrives as a prop.
import { AnimatePresence, LayoutGroup, MotionConfig, motion } from 'motion/react'
import { useCallback, useLayoutEffect, useMemo, useState } from 'react'

import '../styles/leaderboard.css'
import { annotate, heroParts } from '../lib/annotate'
import { fmtInt, fmtPct } from '../lib/format'
import { headshotSrcSet, headshotVariant } from '../lib/media'
import { LENS_META, rankBy, rankDeltas } from '../lib/metrics'
import { thresholdStops } from '../lib/threshold'
import type { Counts } from '../lib/types'
import { useViewState } from '../lib/url'
import { BoardRow } from './BoardRow'
import { LensTabs } from './LensTabs'
import { MethodNote } from './MethodNote'
import { SentimentBar } from './SentimentBar'
import { Stamp } from './Stamp'
import { ThresholdControl } from './ThresholdControl'

export interface BoardPlayer extends Counts {
  name: string
  slug: string
  abbr: string | null
  position: string | null
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

// Polarization is both poles at once: first name heat, the rest ice, as
// the wordmark splits. The link still reads as the whole name.
function SplitName({ name }: { name: string }) {
  const [first, ...rest] = name.split(' ')
  return (
    <>
      <span className="lb__who-heat">{first}</span>
      {rest.length > 0 && <> <span className="lb__who-ice">{rest.join(' ')}</span></>}
    </>
  )
}

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
  const custom = n !== official
  const meta = LENS_META[lens]
  const notes = annotate(input)
  const fade = { initial: { opacity: 0, y: 14 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: -10 }, transition: { duration: 0.22 } }

  const [copied, setCopied] = useState(false)
  const copy = useCallback(() => {
    navigator.clipboard.writeText(window.location.href).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    })
  }, [])

  return (
    <MotionConfig reducedMotion="user">
      <section className="lb" aria-label="Leaderboard">
        <header className={`lb__hero lb__hero--${lens}`}>
          <div className="lb__hero-text">
            <p className="lb__kicker mono">
              {fmtInt(headline.count)} comments about {headline.players} players · {season}
            </p>
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={`${lens}-${leader?.row.slug ?? 'none'}`} className="lb__hero-body" {...fade}>
                <h2 className="lb__sentence">
                  <span className="lb__lead">{hero.before}</span>
                  {leader && (
                    <a className="lb__who" href={`/player/${leader.row.slug}/`}>
                      {lens === 'polar' ? <SplitName name={leader.row.name} /> : leader.row.name}
                    </a>
                  )}
                  {custom && leader && <Stamp kind="unofficial" />}
                </h2>
                {leader && (
                  <>
                    <p className="lb__figure">
                      <span className="lb__big">{meta.kind === 'rate' ? fmtPct(meta.value(leader.row)) : fmtInt(meta.value(leader.row))}</span>
                      <span className="lb__unit mono">{meta.unit}</span>
                    </p>
                    <SentimentBar counts={leader.row} size="hero" subject={leader.row.name} />
                    <p className="lb__meta mono">
                      n={fmtInt(leader.row.total)} comments about {leader.row.name}
                    </p>
                  </>
                )}
              </motion.div>
            </AnimatePresence>
          </div>
          <div className="lb__hero-figure" aria-hidden="true">
            <span className="lb__rank-ghost">1</span>
            <AnimatePresence mode="popLayout" initial={false}>
              {leader && (
                <motion.img
                  key={leader.row.slug}
                  src={headshotVariant(leader.row.headshot, 840)}
                  srcSet={headshotSrcSet(leader.row.headshot, [180, 420, 840])}
                  sizes="(min-width: 761px) 400px, 88px"
                  alt=""
                  width="840"
                  height="614"
                  decoding="async"
                  initial={{ opacity: 0, x: 24 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -24 }}
                  transition={{ duration: 0.3 }}
                />
              )}
            </AnimatePresence>
          </div>
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

      <MethodNote kind="read-first">{notes.join(' ')}</MethodNote>

      <LayoutGroup>
      <motion.ol id="lens-panel" className="lb__rows" role="tabpanel" aria-labelledby={`lens-tab-${lens}`} layout>
        {shown.map((r) => (
          <BoardRow
            key={r.row.slug}
            rank={r.rank}
            official={r.row.total >= official}
            name={r.row.name}
            slug={r.row.slug}
            abbr={r.row.abbr}
            position={r.row.position}
            headshot={r.row.headshot}
            counts={r.row}
            lens={lens}
            scale={maxTotal ? r.row.total / maxTotal : 1}
            delta={deltas?.get(r.row.slug) ?? null}
          />
        ))}
      </motion.ol>
      </LayoutGroup>

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
    </MotionConfig>
  )
}
