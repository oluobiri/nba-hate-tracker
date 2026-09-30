// The play-by-play's last few lines, newest at the bottom, each stamped on
// the game clock: the thing that says what just happened. Static text; the
// score bug beside it is the accessible summary, so no live region.
import type { TickerLine } from '../../lib/replay'

export interface TickerProps {
  lines: TickerLine[]
}

export function Ticker({ lines }: TickerProps) {
  return (
    <ol className="tk" aria-label="The last plays">
      {lines.length === 0 ? (
        <li className="tk__line tk__line--empty">Waiting for the tip.</li>
      ) : (
        lines.map((l) => (
          <li key={l.key} className="tk__line">
            <span className="tk__stamp mono">{l.stamp}</span>
            <span className="tk__text">{l.text}</span>
          </li>
        ))
      )}
    </ol>
  )
}
