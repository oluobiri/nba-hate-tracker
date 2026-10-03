// The replay island: the stage. Fetches the recap file on hydration, builds
// the timeline and the room once, and plays the game on the game clock with
// the room arriving beside it. One island covers the whole stage: the score
// bug, the strip, the gauge, the court, the room and the box score.
import '../../styles/replay.css'
import { MotionConfig } from 'motion/react'
import { type KeyboardEvent, type ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { fetchRecap } from '../../data/recap'
import { etTime, lengthPhrase, periodStartsU, playCursor, playStamp, tOfU, uOfT } from '../../lib/clock'
import { fmtInt } from '../../lib/format'
import { negRate } from '../../lib/metrics'
import { captionPlay, commentCursor, emptyLine, type FeedDensity, feedSelection, type FeedView, lastName, type Moment, prepareReplay, recapRows, type ReplayData, RIGHT_NOW, roomByPlayer, sceneAt } from '../../lib/replay'
import type { Counts } from '../../lib/types'
import { useViewState } from '../../lib/url'
import { BoxScore } from './BoxScore'
import { Caption } from './Caption'
import { Court } from './Court'
import { Feed } from './Feed'
import { FlowStrip } from './FlowStrip'
import { NetGauge } from './NetGauge'
import { ScoreBug } from './ScoreBug'
import { usePlayback } from './usePlayback'

export interface ReplayTeam {
  abbr: string
  name: string
  logo: string
}

export interface RecapReplayProps {
  /** The registry key: the file the island fetches. */
  recapKey: string
  name: string
  focusId: number
  away: ReplayTeam
  home: ReplayTeam
  /** His season, every comment. */
  usual: Counts
  /** player_id → attributed_player, for the Everyone view. */
  names: Record<string, string>
  /** Team name → abbreviation, for flair. */
  abbrOf: Record<string, string>
  /** rules.qualified_threshold, the view state's one default. */
  official: number
}

/** A moment holds the caption this long, in real seconds. */
const HOLD = 4.5
/** Playback drops to SLOW_MIN at a moment and eases back over SLOW seconds. */
const SLOW = 2.4
const SLOW_MIN = 0.25
/** Keys step this many replay seconds; Shift multiplies it. */
const STEP = 5
const BIG_STEP = 30
const URL_DEBOUNCE_MS = 150

type Status = 'loading' | 'ready' | 'failed'
type Tab = 'room' | 'box'

const reducedMotion = (): boolean => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

export function RecapReplay({ recapKey, name, focusId, away, home, usual, names, abbrOf, official }: RecapReplayProps) {
  const [status, setStatus] = useState<Status>('loading')
  const [data, setData] = useState<ReplayData | null>(null)
  const [watched, setStarted] = useState(false)
  const [view, setView] = useState<FeedView>('him')
  const [density, setDensity] = useState<FeedDensity>('top')
  const [tab, setTab] = useState<Tab>('room')
  const [hot, setHot] = useState<{ m: Moment; at: number } | null>(null)
  const hotRef = useRef<{ m: Moment; at: number } | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const urlTimer = useRef(0)
  const settled = useRef(false)

  const defaults = useMemo(() => ({ threshold: official }), [official])
  const [urlState, update, ready] = useViewState(defaults)

  useEffect(() => {
    let live = true
    fetchRecap(recapKey)
      .then((doc) => {
        if (!live) return
        setData(prepareReplay(recapRows(doc), focusId))
        setStatus('ready')
      })
      .catch((e: unknown) => {
        if (!live) return
        console.error(`[replay] ${recapKey}: ${e instanceof Error ? e.message : String(e)}`)
        setStatus('failed')
        document.documentElement.classList.remove('has-replay-view')
      })
    return () => {
      live = false
    }
  }, [recapKey, focusId])

  const tl = data?.tl ?? null
  useEffect(() => () => clearTimeout(urlTimer.current), [])
  const onSettle = useCallback(
    (u: number) => {
      if (!tl) return
      clearTimeout(urlTimer.current)
      urlTimer.current = window.setTimeout(() => update({ t: tOfU(tl, u) }, { replace: true }), URL_DEBOUNCE_MS)
    },
    [tl, update],
  )
  const slowFactor = useCallback(() => {
    const h = hotRef.current
    if (!h || reducedMotion()) return 1
    const age = (performance.now() - h.at) / 1000
    return age < SLOW ? SLOW_MIN + (1 - SLOW_MIN) * (age / SLOW) ** 2 : 1
  }, [])
  const onAdvance = useCallback(
    (from: number, to: number) => {
      if (!data) return
      const a = playCursor(data.tl, from)
      const b = playCursor(data.tl, to)
      for (let i = b; i > a; i--) {
        const m = data.moments.get(i)
        if (m) {
          const next = { m, at: performance.now() }
          hotRef.current = next
          setHot(next)
          return
        }
      }
    },
    [data],
  )
  const playback = usePlayback(tl, { onSettle, slowFactor, onAdvance })
  const { u, playing, speed } = playback

  // A moment lifts after its hold.
  useEffect(() => {
    if (!hot) return
    const id = window.setTimeout(() => {
      if (hotRef.current === hot) {
        hotRef.current = null
        setHot(null)
      }
    }, HOLD * 1000)
    return () => clearTimeout(id)
  }, [hot])

  // A deep link opens paused at its moment: it counts as watched, with no Watch card.
  const started = watched || urlState.t !== null

  // The deep link takes over once, after the file and the URL are both read.
  useLayoutEffect(() => {
    if (!data || !ready || settled.current) return
    settled.current = true
    if (urlState.t !== null) playback.seek(uOfT(data.tl, urlState.t))
    document.documentElement.classList.remove('has-replay-view')
  }, [data, ready, urlState.t, playback])

  // The phone's sticky stack measures itself; the desk's side panels end where the court ends.
  useEffect(() => {
    const el = root.current
    if (!el) return
    const measure = () => {
      const h = (sel: string) => el.querySelector<HTMLElement>(sel)?.getBoundingClientRect().height ?? 0
      const b = h('.bug')
      const c = h('.center')
      const f = h('.flow')
      el.style.setProperty('--replay-bug-h', `${b}px`)
      el.style.setProperty('--replay-flow-top', `${b + c}px`)
      el.style.setProperty('--replay-tabs-top', `${b + c + f}px`)
      el.style.setProperty('--replay-stage-h', `${c}px`)
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    for (const child of el.children) ro.observe(child)
    return () => ro.disconnect()
  }, [])

  const seek = useCallback(
    (at: number) => {
      hotRef.current = null
      setHot(null)
      setStarted(true)
      playback.seek(at)
    },
    [playback],
  )
  const onWatch = () => {
    setStarted(true)
    playback.play()
    const el = root.current
    if (!el) return
    // The stage to the top of the window, under the sticky site header.
    const header = parseFloat(getComputedStyle(el).getPropertyValue('--replay-top')) || 0
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - header, behavior: reducedMotion() ? 'auto' : 'smooth' })
    // The Watch button unmounts with its card; the keys stay on the stage.
    el.focus({ preventScroll: true })
  }
  const onTabKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    const next: Tab = tab === 'room' ? 'box' : 'room'
    setTab(next)
    ;(e.currentTarget.querySelector<HTMLElement>(`#replay-tab-${next}`) ?? null)?.focus()
    e.preventDefault()
    e.stopPropagation()
  }
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.defaultPrevented || e.altKey || e.metaKey || e.ctrlKey || !data) return
    const target = e.target as HTMLElement
    // A focused control keeps its own keys: a tab's arrows, a button's space, a link's enter.
    if (target.tagName === 'BUTTON' || target.tagName === 'A' || target.tagName === 'INPUT') return
    const step = e.shiftKey ? BIG_STEP : STEP
    if (e.code === 'Space') {
      if (e.repeat) return
      setStarted(true)
      playback.toggle()
    } else if (e.key === 'ArrowRight') seek(u + step)
    else if (e.key === 'ArrowLeft') seek(u - step)
    else if (e.key === 'Home') seek(0)
    else if (e.key === 'End') seek(data.tl.totalU)
    else return
    e.preventDefault()
  }

  const scene = useMemo(() => (data ? sceneAt(data, u) : null), [data, u])
  const cursor = scene?.cursor ?? -1
  const selection = useMemo(() => (data ? feedSelection(data.room, view, density, speed) : null), [data, view, density, speed])
  // The box updates per play, not per frame.
  const roomByPlayerNow = useMemo(() => (data ? roomByPlayer(data.room, commentCursor(data.room, data.tl.playU[cursor] ?? 0)) : new Map<number, Counts>()), [data, cursor])
  const nameMap = useMemo(() => new Map(Object.entries(names).map(([k, v]) => [Number(k), v])), [names])
  const abbrMap = useMemo(() => new Map(Object.entries(abbrOf)), [abbrOf])
  const focusTeam = data?.stints.find((s) => s.person_id === focusId)?.team_tricode ?? ''
  const short = data ? lastName(data.focusName) : name.split(' ').slice(-1)[0]!

  const overlay = (() => {
    if (status === 'failed') return <Card big="The replay could not load" small="The quarters and the verdict below tell the night." />
    if (!data || !scene)
      return (
        <Card big="The room, replayed" small="Loading the thread…">
          <noscript className="card__sm">The replay needs JavaScript; the quarters and the verdict below tell the night.</noscript>
        </Card>
      )
    if (!started)
      return (
        <Card big="The room, replayed" small={`${name} · every shot, every play, the comments as they landed · ${lengthPhrase(data.tl)}`}>
          <button type="button" className="card__start" onClick={onWatch} data-testid="watch">
            ▶ Watch the replay
          </button>
        </Card>
      )
    if (u >= data.tl.endU) return <Card big={`Final · ${away.abbr} ${scene.score.away} – ${scene.score.home} ${home.abbr}`} small="The room keeps talking after the buzzer." />
    if (scene.card) return <Card big={scene.card.label} small={`${away.abbr} ${scene.score.away} – ${scene.score.home} ${home.abbr} · ${scene.card.kind === 'halftime' ? 'teams switch ends · ' : ''}the room keeps talking`} />
    return null
  })()

  const caption = (() => {
    if (!data || !scene) return { stamp: '—', text: 'Loading the thread…', his: false }
    const p = captionPlay(data.plays, scene.cursor)
    if (!p) return { stamp: `${scene.clock.label} ${scene.clock.time}`, text: `Tip-off at ${etTime(data.tl.tip)}.`, his: false }
    return { stamp: playStamp(p), text: p.description, his: p.is_focus }
  })()
  const hotShown = hot?.m ?? null
  const hotStamp = hotShown && data ? playStamp(data.plays[hotShown.i]!) : caption.stamp

  return (
    <MotionConfig reducedMotion="user">
      <div ref={root} className={`replay replay--${tab}`} role="region" aria-label="The replay" tabIndex={-1} onKeyDown={onKey} data-status={status}>
        <ScoreBug
          away={away}
          home={home}
          score={scene?.score ?? { away: 0, home: 0 }}
          clock={scene?.clock ?? { label: 'Q1', time: '12:00', period: 1 }}
          line={scene?.line ?? []}
          his={{ name, short, line: scene?.his.line ?? emptyLine(), onFloor: scene?.his.onFloor ?? false }}
          playing={playing}
          speed={speed}
          onToggle={() => {
            setStarted(true)
            playback.toggle()
          }}
          onSpeed={playback.setSpeed}
        />
        {data && (
          <FlowStrip
            series={data.flow}
            periodStarts={periodStartsU(data.tl)}
            endU={data.tl.endU}
            totalU={data.tl.totalU}
            usual={negRate(usual)}
            u={u}
            onSeek={seek}
            subject={short}
            valueText={scene ? `${scene.clock.label} ${scene.clock.time}` : ''}
          />
        )}
        <NetGauge now={scene?.now ?? empty} window={RIGHT_NOW} soFar={scene?.soFar ?? empty} season={usual} />
        <div className="center">
          <Court
            plays={data?.plays ?? []}
            playU={data?.tl.playU ?? []}
            cursor={scene?.cursor ?? -1}
            u={u}
            focusId={focusId}
            focusTeam={focusTeam}
            away={away.abbr}
            home={home}
            ends={data && scene ? (data.ends.get(scene.clock.period) ?? null) : null}
            onFloor={scene?.onFloor ?? new Set()}
            order={data?.order ?? new Map()}
            names={data?.names ?? new Map()}
            blocked={data?.blocked ?? new Map()}
            hot={hotShown}
          >
            {overlay}
          </Court>
          <Caption stamp={hotStamp} text={caption.text} his={caption.his} hot={hotShown} who={short.toUpperCase()} hold={HOLD} />
          <NetGauge now={scene?.now ?? empty} window={RIGHT_NOW} soFar={scene?.soFar ?? empty} season={usual} orientation="horizontal" />
        </div>
        <div className="replay__tabs" role="tablist" aria-label="The room or the box score" onKeyDown={onTabKey}>
          <button type="button" role="tab" id="replay-tab-room" className="replay__tab" aria-selected={tab === 'room'} aria-controls="replay-room" tabIndex={tab === 'room' ? 0 : -1} onClick={() => setTab('room')}>
            The room
          </button>
          <button type="button" role="tab" id="replay-tab-box" className="replay__tab" aria-selected={tab === 'box'} aria-controls="replay-box" tabIndex={tab === 'box' ? 0 : -1} onClick={() => setTab('box')}>
            Box
          </button>
        </div>
        {data && selection && (
          <Feed room={data.room} selection={selection} u={u} view={view} density={density} onView={setView} onDensity={setDensity} focusId={focusId} names={nameMap} abbrOf={abbrMap} tipLine={`Tip-off at ${etTime(data.tl.tip)}.`} />
        )}
        {data && scene && (
          <BoxScore
            teams={[
              { abbr: away.abbr, score: scene.score.away, ids: data.order.get(away.abbr) ?? [] },
              { abbr: home.abbr, score: scene.score.home, ids: data.order.get(home.abbr) ?? [] },
            ]}
            lines={scene.lines}
            names={data.names}
            onFloor={scene.onFloor}
            focusId={focusId}
            room={roomByPlayerNow}
          />
        )}
        <p className="visually-hidden">{status === 'ready' ? `${fmtInt(data?.room.focus.length ?? 0)} comments about ${name} in the live thread.` : ''}</p>
      </div>
    </MotionConfig>
  )
}

const empty: Counts = { neg: 0, neu: 0, pos: 0, total: 0 }

function Card({ big, small, children }: { big: string; small: string; children?: ReactNode }) {
  return (
    <div className="card">
      <div className="card__big">{big}</div>
      <div className="card__sm">{small}</div>
      {children}
    </div>
  )
}
