// The race: one island. The hero (the leader so far and the week), the play
// button, the two toggles, the scrubber and the board move together on one
// week. It opens paused on the final week, which is the leaderboard; play
// restarts from the first. The toggles and the week live in the query string,
// the week written when playback settles, never per frame.
import { AnimatePresence, MotionConfig, useReducedMotion } from 'motion/react'
import { type CSSProperties, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import '../styles/race.css'
import { fmtInt, fmtPct } from '../lib/format'
import { headshotVariant } from '../lib/media'
import { cumulate, everTop, movement, raceLead, rankFrame, unpackCounts } from '../lib/race'
import { type RaceBy, type RaceMode, useViewState } from '../lib/url'
import type { PhaseBand } from '../lib/weeks'
import { RaceRow } from './RaceRow'

export interface RacePlayer {
  name: string
  slug: string
  abbr: string | null
  headshot: string
}

export interface RaceWeek {
  /** The week's Monday: "Feb 23". */
  label: string
  /** The season phase, "Season final" on the last week. */
  phase: string
}

export interface RaceProps {
  /** The field: every player at or above the official minimum. */
  players: RacePlayer[]
  weeks: RaceWeek[]
  /** Weekly counts, packed by `packCounts`: players × weeks × (neg, neu, pos). */
  counts: string
  bands: PhaseBand[]
  /** Calendar marks under the scrubber, each at a week's index. */
  marks: { label: string; at: number }[]
  /** rules.floors.race_entry_min_n */
  entry: number
  /** rules.qualified_threshold, the view state's one default. */
  official: number
}

// Page choices, not rules: the rows shown, a week's time on screen, a seek's travel.
const TOP = 10
const STEP_MS = 900
const SEEK_S = 0.25
// A band narrower than this many weeks goes unlabelled.
const BAND_LABEL_WEEKS = 5

const MODES: readonly { key: RaceMode; label: string }[] = [
  { key: 'hated', label: 'Hated' },
  { key: 'loved', label: 'Loved' },
]
const MEASURES: readonly { key: RaceBy; label: string }[] = [
  { key: 'rate', label: 'Rate' },
  { key: 'count', label: 'Count' },
]

export function Race({ players, weeks, counts, bands, marks, entry, official }: RaceProps) {
  const defaults = useMemo(() => ({ threshold: official }), [official])
  const [view, update, ready] = useViewState(defaults)
  const { mode, by } = view
  const last = weeks.length - 1
  const reduce = useReducedMotion()

  // A deep link's prerendered default stays hidden until the URL is in.
  useLayoutEffect(() => {
    if (ready) document.documentElement.classList.remove('has-race-view')
  }, [ready])

  const frames = useMemo(() => cumulate(unpackCounts(counts, players.length, weeks.length)), [counts, players.length, weeks.length])

  // The week while it plays; null when paused, and the URL's week shows.
  const [live, setLive] = useState<number | null>(null)
  const [ran, setRan] = useState(false)
  const playing = live !== null
  const w = live ?? Math.min(last, view.w ?? last)
  const isLast = w === last

  const settle = useCallback(
    (week: number) => {
      update({ w: week >= last ? null : week }, { replace: true })
      setLive(null)
    },
    [update, last],
  )
  const seek = useCallback((week: number) => settle(Math.max(0, Math.min(last, week))), [settle, last])
  const toggle = useCallback(() => {
    if (playing) return settle(w)
    setRan(true)
    setLive(isLast ? 0 : w)
  }, [playing, settle, w, isLast])

  // One week per step; the last week holds a step, then playback settles there.
  useEffect(() => {
    if (live === null) return
    const id = window.setTimeout(() => (live >= last ? settle(last) : setLive(live + 1)), STEP_MS)
    return () => window.clearTimeout(id)
  }, [live, last, settle])

  // Space plays and pauses, the arrows step; a focused control keeps its own keys.
  const keys = useRef({ toggle, seek, w, playing })
  useLayoutEffect(() => {
    keys.current = { toggle, seek, w, playing }
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return
      if ((e.target as HTMLElement | null)?.closest('button, a, input, select, textarea, summary')) return
      const k = keys.current
      if (e.key === ' ') {
        e.preventDefault()
        k.toggle()
      } else if (e.key === 'ArrowRight') k.seek(k.w + 1)
      else if (e.key === 'ArrowLeft') k.seek(k.w - 1)
    }
    const onHide = () => {
      if (document.hidden && keys.current.playing) keys.current.seek(keys.current.w)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('visibilitychange', onHide)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('visibilitychange', onHide)
    }
  }, [])

  // Once a race has played, fetch the faces it will need, so a newcomer never pops in.
  useEffect(() => {
    if (!ran) return
    for (const i of everTop(frames, mode, by, entry, TOP)) new Image().src = headshotVariant(players[i]!.headshot, 180)
  }, [ran, frames, mode, by, entry, players])

  const ranked = useMemo(() => rankFrame(frames[w]!, mode, by, entry), [frames, w, mode, by, entry])
  const moves = useMemo(() => movement(ranked, w > 0 ? rankFrame(frames[w - 1]!, mode, by, entry) : null), [ranked, frames, w, mode, by, entry])
  const top = ranked.slice(0, TOP)
  const lead = top[0] ?? null
  const leader = lead ? players[lead.i]! : null
  const word = mode === 'hated' ? 'negative' : 'positive'
  const fmt = (v: number): string => (by === 'rate' ? fmtPct(v) : fmtInt(v))

  const travel = reduce ? 0 : playing ? STEP_MS / 1000 : SEEK_S
  const count = reduce || !playing ? 0 : STEP_MS / 1000
  const week = weeks[w]!
  const playLabel = playing ? '❚❚ Pause' : isLast ? (ran ? '↺ Replay' : '▶ Play the season') : '▶ Play'
  const entered = by === 'rate' ? `${ranked.length} of ${players.length} players have ${fmtInt(entry)} comments` : `${players.length} players`

  return (
    <MotionConfig reducedMotion="user">
      <section className={`race race--${mode}`} aria-label="The race">
        <header className="race__hero">
          <div className="race__lead">
            <h2 className="race__sentence">
              <span className="race__so-far">{raceLead(mode, by, isLast)}</span>
              {leader ? (
                <a className="race__who" href={`/player/${leader.slug}/`} style={{ '--chars': leader.name.length } as CSSProperties} data-testid="race-leader">
                  {leader.name}
                </a>
              ) : (
                <span className="race__who">—</span>
              )}
            </h2>
            {lead && (
              <p className="race__fig mono">
                {by === 'rate' ? (
                  <>
                    <b>{fmt(lead.value)}</b> of {fmtInt(lead.n)} comments {word}
                  </>
                ) : (
                  <>
                    <b>{fmt(lead.value)}</b> {word} comments of {fmtInt(lead.n)}
                  </>
                )}
              </p>
            )}
          </div>
          <div className="race__when">
            <p className="eyebrow" data-testid="race-week">
              {week.phase} · week {w + 1} of {weeks.length}
            </p>
            <p className="race__date">{week.label}</p>
            <p className="race__sub mono">every comment through that week</p>
          </div>
        </header>

        <div className="race__controls">
          <button type="button" className={`btn race__play${playing ? '' : ' race__play--go'}`} onClick={toggle} data-testid="race-play">
            {playLabel}
          </button>
          <div className="race__seg" role="group" aria-label="Sentiment">
            {MODES.map((m) => (
              <button key={m.key} type="button" className={`btn race__mode race__mode--${m.key}`} aria-pressed={m.key === mode} onClick={() => update({ mode: m.key })}>
                {m.label}
              </button>
            ))}
          </div>
          <div className="race__seg" role="group" aria-label="Measure">
            {MEASURES.map((m) => (
              <button key={m.key} type="button" className="btn" aria-pressed={m.key === by} onClick={() => update({ by: m.key })}>
                {m.label}
              </button>
            ))}
          </div>
        </div>

        <div className="race__scrub">
          <input
            className="race__range"
            type="range"
            min={0}
            max={last}
            step={1}
            value={w}
            aria-label="Week"
            aria-valuetext={`Week of ${week.label}, week ${w + 1} of ${weeks.length}${leader ? `, ${leader.name} leads` : ''}`}
            style={{ '--p': `${last ? (100 * w) / last : 0}%` } as CSSProperties}
            onChange={(e) => seek(Number(e.target.value))}
            data-testid="race-scrub"
          />
          <div className="race__bands" aria-hidden="true">
            {bands.map((b) => (
              <span key={b.start} className="race__band" style={{ left: `${(100 * b.start) / weeks.length}%`, width: `${(100 * (b.end - b.start)) / weeks.length}%` }}>
                {b.end - b.start >= BAND_LABEL_WEEKS ? b.label : ''}
              </span>
            ))}
          </div>
          <div className="race__marks" aria-hidden="true">
            {marks.map((m) => (
              <span key={m.label} className="race__mark mono" style={{ left: `${(100 * (m.at + 0.5)) / weeks.length}%` }}>
                {m.label}
              </span>
            ))}
          </div>
        </div>

        <ol className="race__rows" aria-label={`The top ${TOP} through the week of ${week.label}`}>
          <AnimatePresence initial={false} mode="popLayout">
            {top.map((r, k) => {
              const p = players[r.i]!
              return (
                <RaceRow
                  key={p.slug}
                  presence
                  rank={k + 1}
                  name={p.name}
                  slug={p.slug}
                  abbr={p.abbr}
                  headshot={p.headshot}
                  mode={mode}
                  by={by}
                  value={r.value}
                  n={r.n}
                  share={lead && lead.value ? r.value / lead.value : 0}
                  move={moves.get(r.i) ?? null}
                  travel={travel}
                  count={count}
                />
              )
            })}
          </AnimatePresence>
        </ol>

        <p className="race__status mono">
          <span>
            {entered} · the top {Math.min(TOP, ranked.length)} shown
          </span>
          <a href={mode === 'loved' ? '/?lens=pos' : '/'}>See the final leaderboard →</a>
        </p>
      </section>
    </MotionConfig>
  )
}
