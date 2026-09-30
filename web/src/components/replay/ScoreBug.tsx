// The replay's anchor: away at home, the score, the period and the game
// clock, the wall clock in ET, and why the clock stands still when it does.
// His team bone, the opponent mute, never team colours. Play/pause and the
// speed presets live here so they stay with the score at every width; the
// island slots the right-now bar in on a phone.
import type { ReactNode } from 'react'

import { SPEEDS, type Speed } from '../../lib/clock'
import { fmtInt } from '../../lib/format'
import type { Line } from '../../lib/replay'

export interface BugSide {
  abbr: string
  /** null before the file arrives. */
  score: number | null
}

export interface ScoreBugProps {
  away: BugSide
  home: BugSide
  /** Which side is his. */
  his: 'away' | 'home'
  /** His name, for the running line's label. */
  name: string
  /** "Q3", "Halftime"; the moment's label. */
  periodLabel: string
  /** "04:12"; null before the tip. */
  clock: string | null
  /** "TIMEOUT · SAS"; null while the clock runs. */
  stoppage: string | null
  /** "9:47 PM ET"; null before the file arrives. */
  wall: string | null
  line: Line | null
  playing: boolean
  speed: Speed
  /** "the game in 3 min" */
  speedText: string
  onToggle?: () => void
  onSpeed?: (speed: Speed) => void
  children?: ReactNode
}

const score = (v: number | null): string => (v === null ? '—' : fmtInt(v))

export function ScoreBug({ away, home, his, name, periodLabel, clock, stoppage, wall, line, playing, speed, speedText, onToggle, onSpeed, children }: ScoreBugProps) {
  const side = (which: 'away' | 'home') => (which === his ? 'bug__team bug__team--his' : 'bug__team')
  return (
    <div className="bug">
      <div className="bug__game">
        <p className="bug__teams">
          <span className="visually-hidden">{`${away.abbr} ${score(away.score)} at ${home.abbr} ${score(home.score)}.`}</span>
          <span className={side('away')} aria-hidden="true">
            {away.abbr}
          </span>
          <span className="bug__score" aria-hidden="true">
            {score(away.score)}
          </span>
          <span className="bug__at" aria-hidden="true">
            @
          </span>
          <span className="bug__score" aria-hidden="true">
            {score(home.score)}
          </span>
          <span className={side('home')} aria-hidden="true">
            {home.abbr}
          </span>
        </p>
        <p className="bug__clock mono">
          <span className="bug__period">{periodLabel}</span>
          <span className="bug__time">{clock ?? '--:--'}</span>
          {stoppage && <span className="bug__stop">{stoppage}</span>}
          <span className="bug__wall">{wall ?? '—'}</span>
        </p>
        <p className="bug__line mono">
          <span className="bug__who">{name}</span>
          {line ? ` ${fmtInt(line.pts)} pts · ${fmtInt(line.reb)} reb · ${fmtInt(line.ast)} ast` : ' no line yet'}
        </p>
      </div>
      <div className="bug__controls">
        <button type="button" className="btn bug__toggle" aria-pressed={playing} onClick={onToggle} disabled={!onToggle}>
          {playing ? 'Pause' : 'Play'}
        </button>
        <div className="bug__speeds" role="group" aria-label="Speed">
          {SPEEDS.map((s) => (
            <button key={s} type="button" className="btn btn--small" aria-pressed={s === speed} onClick={() => onSpeed?.(s)} disabled={!onSpeed}>
              {s}×
            </button>
          ))}
        </div>
        <span className="bug__pace mono">{speedText}</span>
      </div>
      {children}
    </div>
  )
}
