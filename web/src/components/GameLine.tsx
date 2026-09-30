// One game as an eyebrow reads it: the round, the game number, away at
// home with the winner bold and the loser gray (never a colour), the date.
import type { GameLineParts, GameSide } from '../lib/games'

const Side = ({ side }: { side: GameSide }) => (
  <span className={`gline__side gline__side--${side.won ? 'w' : 'l'}`}>
    {side.abbr} {side.score}
  </span>
)

export function GameLine({ parts }: { parts: GameLineParts }) {
  return (
    <span className="gline">
      {parts.round}
      {parts.game && <> · {parts.game}</>}
      {' · '}
      <Side side={parts.away} /> @ <Side side={parts.home} />
      {' · '}
      {parts.date}
    </span>
  )
}
