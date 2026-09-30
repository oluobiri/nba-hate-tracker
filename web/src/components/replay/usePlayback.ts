// The playback loop. Position lives in refs and advances in playback units
// per real second times the speed; `t` (wall seconds since tip) is committed
// to React state only when the integer changes and at most every few
// frames. Pauses when the tab is hidden and never resumes on its own; the
// URL is written by the island on pause, seek, step and speed, never here.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { defaultSpeed, fromPlayback, type Speed, type Timeline, toPlayback } from '../../lib/clock'

/** Commits per second the loop makes, at most: a page choice. */
const COMMIT_MS = 50

export interface Playback {
  t: number
  playing: boolean
  speed: Speed
  toggle: () => void
  play: () => void
  pause: () => void
  /** Jump to t; keeps playing if it was. */
  seek: (t: number) => void
  step: (delta: number) => void
  setSpeed: (speed: Speed) => void
}

export function usePlayback(tl: Timeline | null, onSettle: (t: number) => void): Playback {
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  // The preset is the timeline's default until the reader picks one.
  const [chosen, setChosen] = useState<Speed | null>(null)
  const speed: Speed = chosen ?? (tl ? defaultSpeed(tl) : 60)
  const pos = useRef(0)
  const last = useRef(0)
  const committed = useRef(0)
  const raf = useRef(0)
  const speedRef = useRef(speed)
  const settle = useRef(onSettle)
  useLayoutEffect(() => {
    speedRef.current = speed
    settle.current = onSettle
  })

  const stop = useCallback(() => {
    cancelAnimationFrame(raf.current)
    raf.current = 0
  }, [])

  const commit = useCallback(
    (now: number) => {
      if (!tl) return
      committed.current = now
      setT(fromPlayback(tl, pos.current))
    },
    [tl],
  )

  const pause = useCallback(() => {
    if (!raf.current) return
    stop()
    setPlaying(false)
    if (tl) {
      const at = fromPlayback(tl, pos.current)
      setT(at)
      settle.current(at)
    }
  }, [stop, tl])

  const play = useCallback(() => {
    if (!tl || raf.current) return
    if (pos.current >= tl.length) pos.current = 0
    last.current = performance.now()
    committed.current = 0
    setPlaying(true)
    const tick = (now: number) => {
      pos.current += ((now - last.current) / 1000) * speedRef.current
      last.current = now
      if (pos.current >= tl.length) {
        pos.current = tl.length
        raf.current = 0
        setPlaying(false)
        commit(now)
        settle.current(tl.total)
        return
      }
      if (now - committed.current >= COMMIT_MS) commit(now)
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
  }, [tl, commit])

  const seek = useCallback(
    (to: number) => {
      if (!tl) return
      const at = Math.max(0, Math.min(tl.total, Math.round(to)))
      pos.current = toPlayback(tl, at)
      setT(at)
      settle.current(at)
    },
    [tl],
  )

  const step = useCallback(
    (delta: number) => {
      if (!tl) return
      seek(fromPlayback(tl, pos.current) + delta)
    },
    [tl, seek],
  )

  const setSpeed = useCallback(
    (s: Speed) => {
      speedRef.current = s
      setChosen(s)
      if (tl) settle.current(fromPlayback(tl, pos.current))
    },
    [tl],
  )

  const toggle = useCallback(() => {
    if (raf.current) pause()
    else play()
  }, [pause, play])

  useEffect(() => {
    const onHide = () => {
      if (document.hidden) pause()
    }
    document.addEventListener('visibilitychange', onHide)
    return () => {
      document.removeEventListener('visibilitychange', onHide)
      stop()
    }
  }, [pause, stop])

  return { t, playing, speed, toggle, play, pause, seek, step, setSpeed }
}
