// The lead recap in the leaderboard's hero form: the game line as the
// kicker, the name in display type coloured by the night against his usual,
// the hook as the sentence, his line and the counts, the period strip, and
// one play affordance. The masked headshot at the right; a card on a phone.
import { headshotSrcSet, headshotVariant } from '../lib/media'
import { boxLine, countsLine, recapHref, type Recap } from '../lib/recaps'
import { GameLine } from './GameLine'
import { PeriodStrip } from './PeriodStrip'

export interface RecapLeadProps {
  recap: Recap
}

export function RecapLead({ recap }: RecapLeadProps) {
  const name = recap.entry.attributed_player
  const headshot = recap.player.headshot_url
  return (
    <header className={`hero hero--${recap.tone} hero--card hero--recap`}>
      <div className="hero__text">
        <p className="hero__kicker mono">
          <GameLine parts={recap.line} />
        </p>
        <h2 className="hero__sentence">
          <span className="hero__lead">The room on</span>
          <span className="hero__who">{name}</span>
        </h2>
        <p className="hero__hook">{recap.hook}</p>
        <p className="hero__meta mono">
          {boxLine(recap.box)} · {countsLine(recap.entry)}
        </p>
        <PeriodStrip cells={recap.cells} size="hero" subject={name} />
        <a className="btn hero__play" href={recapHref(recap.key)}>
          Open the recap
        </a>
      </div>
      <div className="hero__figure" aria-hidden="true">
        <img src={headshotVariant(headshot, 840)} srcSet={headshotSrcSet(headshot, [180, 420, 840])} sizes="(min-width: 761px) 400px, 96px" alt="" width="840" height="614" decoding="async" />
      </div>
    </header>
  )
}
