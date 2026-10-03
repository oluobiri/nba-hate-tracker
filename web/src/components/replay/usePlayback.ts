// The playback loop: replay seconds advanced by requestAnimationFrame at the
// chosen speed, slowed by a factor the island supplies (his moments). The
// position lives in a ref and is committed to React state a few times a
// second; the loop never restarts on a render. Pauses when the tab hides.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { Speed, Timeline } from '../../lib/clock'

export interface Playback {
  u: number
  playing: boolean
  speed: Speed
  toggle(): void
  play(): void
  pause(): void
  seek(u: number): void
  step(delta: number): void
  setSpeed(s: Speed): void
}

export interface PlaybackOptions {
  /** Called when the position settles: pause, seek, step, the end. Never per frame. */
  onSettle: (u: number) => void
  /** A multiplier on the speed, read every frame: under 1 during a moment. */
  slowFactor: () => number
  /** Called when the position crosses forward while playing, with the old and new position. */
  onAdvance: (from: number, to: number) => void
}

/** How often the position reaches React state, in milliseconds. */
const COMMIT_MS = 50
/** The longest step one frame may take, so a background tab does not leap. */
const MAX_DT = 0.1

export function usePlayback(tl: Timeline | null, opts: PlaybackOptions): Playback {
  const [u, setU] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeedState] = useState<Speed>(1)
  const pos = useRef(0)
  const last = useRef(0)
  const committed = useRef(0)
  const raf = useRef(0)
  const speedRef = useRef<Speed>(1)
  const optsRef = useRef(opts)
  const playingRef = useRef(false)
  const tickRef = useRef<(now: number) => void>(() => {})
  const total = tl?.totalU ?? 0

  useLayoutEffect(() => {
    optsRef.current = opts
    speedRef.current = speed
  })
  const frame = useCallback(() => {
    raf.current = requestAnimationFrame((now) => tickRef.current(now))
  }, [])

  const stop = useCallback(() => {
    cancelAnimationFrame(raf.current)
    playingRef.current = false
    setPlaying(false)
  }, [])

  const commit = useCallback(() => {
    setU(pos.current)
    committed.current = performance.now()
  }, [])

  const tick = useCallback(
    (now: number) => {
      if (!playingRef.current) return
      const dt = Math.min(MAX_DT, (now - last.current) / 1000)
      last.current = now
      const from = pos.current
      pos.current = Math.min(total, from + dt * speedRef.current * optsRef.current.slowFactor())
      if (pos.current > from) optsRef.current.onAdvance(from, pos.current)
      if (pos.current >= total) {
        stop()
        commit()
        optsRef.current.onSettle(pos.current)
        return
      }
      if (now - committed.current >= COMMIT_MS) commit()
      frame()
    },
    [total, stop, commit, frame],
  )
  useLayoutEffect(() => {
    tickRef.current = tick
  }, [tick])

  const play = useCallback(() => {
    if (!tl || playingRef.current) return
    if (pos.current >= total) pos.current = 0
    playingRef.current = true
    setPlaying(true)
    last.current = performance.now()
    frame()
  }, [tl, total, frame])

  const pause = useCallback(() => {
    if (!playingRef.current) return
    stop()
    commit()
    optsRef.current.onSettle(pos.current)
  }, [stop, commit])

  const toggle = useCallback(() => {
    if (playingRef.current) pause()
    else play()
  }, [pause, play])

  const seek = useCallback(
    (at: number) => {
      pos.current = Math.max(0, Math.min(total, at))
      commit()
      optsRef.current.onSettle(pos.current)
    },
    [total, commit],
  )

  const step = useCallback((delta: number) => seek(pos.current + delta), [seek])

  const setSpeed = useCallback((s: Speed) => {
    speedRef.current = s
    setSpeedState(s)
  }, [])

  useEffect(() => {
    const onHide = () => {
      if (document.hidden) pause()
    }
    document.addEventListener('visibilitychange', onHide)
    return () => {
      document.removeEventListener('visibilitychange', onHide)
      cancelAnimationFrame(raf.current)
    }
  }, [pause])

  return { u, playing, speed, toggle, play, pause, seek, step, setSpeed }
}
