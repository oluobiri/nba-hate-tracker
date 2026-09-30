// The replay: one island. It fetches the recap file on hydration (the
// site's one runtime fetch), asserts it against the contract, turns the
// column arrays into rows once, and plays the room on the wall clock. The
// URL carries `t`: a deep link opens paused there, and the scrubber, a
// step, a pause and a speed change write it back with replace. Pre-fetch
// and without JavaScript the frame renders with what the page knows.
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { type KeyboardEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import '../styles/replay.css'
import { fetchRecap } from '../data/recap'
import type { RecapPlaysRow } from '../data/types.gen'
import { buildTimeline, etTime, phaseAt, playCursor, speedPhrase, stoppageAt, stoppageLabel, type Timeline, wallStamp } from '../lib/clock'
import { lagPhrase, type PeriodCell, periodLabel } from '../lib/recaps'
import {
  breakCard,
  buildRoom,
  clockAt,
  commentCursor,
  commentStamp,
  type Density,
  feed,
  type FeedView,
  lineAt,
  prepareComments,
  quarterBox,
  recapRows,
  type ReplayComment,
  RIGHT_NOW,
  rightNow,
  type Room,
  roomByPeriod,
  scoreAt,
  soFar,
  ticker,
} from '../lib/replay'
import type { Counts } from '../lib/types'
import { useViewState } from '../lib/url'
import { Feed } from './replay/Feed'
import { QuarterBox } from './replay/QuarterBox'
import { RoomBars } from './replay/RoomBars'
import { ScoreBug } from './replay/ScoreBug'
import { Scrubber } from './replay/Scrubber'
import { Ticker } from './replay/Ticker'
import { usePlayback } from './replay/usePlayback'
import { SentimentBar } from './SentimentBar'

export interface RecapReplayProps {
  recapKey: string
  name: string
  away: { abbr: string; name: string }
  home: { abbr: string; name: string; logo: string }
  his: 'away' | 'home'
  /** The registry's per-period counts: the room's row before the file arrives. */
  cells: PeriodCell[]
  /** His season counts, for the so-far line. */
  usual: Counts
  /** rules.recaps.reaction_lag.median_offset_seconds; null when unmeasured. */
  lagSeconds: number | null
  /** Team name → abbreviation, for flairs. */
  flairAbbr: Record<string, string>
  /** rules.qualified_threshold, the view state's one default. */
  official: number
}

interface Loaded {
  plays: RecapPlaysRow[]
  tl: Timeline
  room: Room
}

type Status = 'loading' | 'ready' | 'failed'

/** Wall seconds one arrow step moves: a page choice; Shift makes it ten. */
const STEP = 30
/** Feed cards shown before "Show more", and per press: a page choice. */
const FEED_PAGE = 40
/** Wait before a seek reaches the URL, so a drag writes once: a page choice. */
const URL_DEBOUNCE_MS = 150
const WIDE = '(min-width: 900px)'

export function RecapReplay({ recapKey, name, away, home, his, cells, usual, lagSeconds, flairAbbr, official }: RecapReplayProps) {
  const defaults = useMemo(() => ({ threshold: official }), [official])
  const [view, update, ready] = useViewState(defaults)
  const [status, setStatus] = useState<Status>('loading')
  const [data, setData] = useState<Loaded | null>(null)
  const [feedView, setFeedView] = useState<FeedView>('his')
  const [density, setDensity] = useState<Density>('all')
  const [shown, setShown] = useState(FEED_PAGE)
  const region = useRef<HTMLDivElement>(null)
  const more = useRef<HTMLDetailsElement>(null)
  const urlTimer = useRef(0)

  // The URL sees a settled moment, once per drag.
  const onSettle = useCallback(
    (t: number) => {
      clearTimeout(urlTimer.current)
      urlTimer.current = window.setTimeout(() => update({ t }, { replace: true }), URL_DEBOUNCE_MS)
    },
    [update],
  )
  const playback = usePlayback(data?.tl ?? null, onSettle)
  const { t, playing, speed } = playback

  useEffect(() => {
    let live = true
    fetchRecap(recapKey)
      .then((doc) => {
        if (!live) return
        const rows = recapRows(doc)
        const tl = buildTimeline(rows.periods)
        setData({ plays: rows.plays, tl, room: buildRoom(prepareComments(rows.comments, tl, flairAbbr), tl) })
        setStatus('ready')
      })
      .catch((e: unknown) => {
        if (!live) return
        console.error(`[replay] ${recapKey}: ${e instanceof Error ? e.message : String(e)}`)
        setStatus('failed')
      })
    return () => {
      live = false
    }
  }, [recapKey, flairAbbr])

  // Once the file and the URL are both in: a deep link's moment, paused, or
  // the tip and play, unless the reader prefers reduced motion. The frame
  // stays hidden until then, so a deep link never flashes the tip.
  const settled = useRef(false)
  useLayoutEffect(() => {
    if (!data || !ready || settled.current) return
    settled.current = true
    document.documentElement.classList.remove('has-replay-view')
    if (view.t !== null) playback.seek(view.t)
    else if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) playback.play()
  }, [data, ready, view.t, playback])

  // The quarter box opens on a wide screen and stays a control on a phone.
  useEffect(() => {
    if (more.current && window.matchMedia(WIDE).matches) more.current.open = true
  }, [])

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const el = e.target as HTMLElement
    const native = el.closest('button, a, input, select, textarea')
    const stride = e.shiftKey ? STEP * 10 : STEP
    const keys: Record<string, (() => void) | undefined> = {
      ' ': native ? undefined : playback.toggle,
      ArrowLeft: el.tagName === 'INPUT' ? undefined : () => playback.step(-stride),
      ArrowRight: el.tagName === 'INPUT' ? undefined : () => playback.step(stride),
      Home: el.tagName === 'INPUT' ? undefined : () => playback.seek(0),
      End: el.tagName === 'INPUT' ? undefined : () => playback.seek(data?.tl.total ?? 0),
    }
    const go = keys[e.key]
    if (go) {
      e.preventDefault()
      go()
    }
  }

  // Every reading at t: cursors first, then O(1) or O(periods) reads.
  const at = useMemo(() => {
    if (!data) return null
    const { plays, tl, room } = data
    const cursor = playCursor(plays, tl, t)
    const ccursor = commentCursor(room.comments, t)
    const moment = phaseAt(tl, t)
    const items = feed(room, ccursor, feedView, density, shown + 1)
    return {
      cursor,
      ccursor,
      moment,
      score: scoreAt(plays, cursor),
      clock: clockAt(plays, tl, t),
      stoppage: stoppageLabel(stoppageAt(plays, cursor, tl)),
      wall: wallStamp(tl, t),
      line: lineAt(plays, cursor),
      now: rightNow(room, ccursor),
      soFar: soFar(room, ccursor),
      byPeriod: roomByPeriod(room, ccursor),
      box: quarterBox(plays, tl, cursor),
      lines: ticker(plays, cursor),
      items: items.slice(0, shown),
      more: items.length > shown,
      card: moment.phase === 'break' && moment.segment ? breakCard(room, moment.segment) : null,
    }
  }, [data, t, feedView, density, shown])

  const stamp = useCallback((c: ReplayComment) => (data ? commentStamp(data.plays, data.tl, c.t) : ''), [data])
  const wall = useCallback((c: ReplayComment) => (data ? etTime(data.tl.tip + c.t) : ''), [data])
  const lag = lagPhrase(lagSeconds)
  const period = at ? periodLabel(Math.max(1, at.moment.period)) : 'Q1'
  const empty: Counts = { neg: 0, neu: 0, pos: 0, total: 0 }

  return (
    <MotionConfig reducedMotion="user">
      <div ref={region} className={`replay replay--${status}`} role="region" aria-label="The replay" tabIndex={-1} onKeyDown={onKeyDown}>
        <div className="replay__bug">
          <ScoreBug
            away={{ abbr: away.abbr, score: at?.score.away ?? null }}
            home={{ abbr: home.abbr, score: at?.score.home ?? null }}
            his={his}
            name={name}
            periodLabel={period}
            clock={at?.clock ?? null}
            stoppage={at?.stoppage ?? null}
            wall={at?.wall ?? null}
            line={at?.line ?? null}
            playing={playing}
            speed={speed}
            speedText={data ? speedPhrase(data.tl, speed) : ''}
            onToggle={data ? playback.toggle : undefined}
            onSpeed={data ? playback.setSpeed : undefined}
          >
            <div className="replay__now-phone">
              <p className="rb__label mono">
                Right now <span className="rb__detail">{at && at.now.total ? `his last ${Math.min(RIGHT_NOW, at.now.total)}` : 'no comments yet'}</span>
              </p>
              {at && at.now.total > 0 ? <SentimentBar counts={at.now} size="mini" subject={`${name} right now`} /> : <div className="rb__empty" aria-hidden="true" />}
            </div>
          </ScoreBug>
          {data && <Scrubber tl={data.tl} t={t} valueText={`${at?.stoppage ?? `${period} ${at?.clock ?? ''}`} · ${at?.wall ?? ''}`} lag={lag} onSeek={playback.seek} />}
        </div>

        <div className="replay__ticker">
          <Ticker lines={at?.lines ?? []} />
        </div>

        <aside className="replay__side">
          <details ref={more} className="replay__more">
            <summary>The room by quarter</summary>
            <div className="replay__more-body">
              <RoomBars now={at?.now ?? empty} soFar={at?.soFar ?? empty} window={RIGHT_NOW} usual={usual} subject={name} />
              <QuarterBox rows={at?.box ?? []} room={at?.byPeriod ?? cells} away={away.abbr} home={home.abbr} his={his} subject={name} />
            </div>
          </details>
        </aside>

        <div className="replay__feed">
          <AnimatePresence initial={false}>
            {status === 'loading' && (
              <motion.p key="loading" className="replay__note" exit={{ opacity: 0 }}>
                Loading the thread…
              </motion.p>
            )}
          </AnimatePresence>
          {status === 'failed' && <p className="replay__note">The replay could not load; the quarters above tell the arc.</p>}
          <Feed
            items={at?.items ?? []}
            more={at?.more ?? false}
            view={feedView}
            density={density}
            name={name}
            card={at?.card ?? null}
            stamp={stamp}
            wall={wall}
            onView={data ? setFeedView : undefined}
            onDensity={data ? setDensity : undefined}
            onMore={data ? () => setShown((n) => n + FEED_PAGE) : undefined}
          />
        </div>
      </div>
    </MotionConfig>
  )
}
