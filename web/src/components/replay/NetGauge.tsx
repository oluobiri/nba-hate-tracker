// The room on him right now: net sentiment over his last comments, as a
// vertical gauge from +100 to −100 with his season's net as a dashed tick,
// the figure coloured by its strength; under it, so far and his season as a
// net figure over a mix bar. Numbers are net; bars show the mix.
import '../../styles/replay.css'
import type { CSSProperties } from 'react'

import { fmtInt } from '../../lib/format'
import { fmtNet, netFill, netOf, netStyle } from '../../lib/net'
import type { Counts } from '../../lib/types'
import { SentimentBar } from '../SentimentBar'

export interface NetGaugeProps {
  /** His last comments, up to the window. */
  now: Counts
  /** The window's size, for the heading. */
  window: number
  soFar: Counts
  season: Counts
  /** The phone's form: a horizontal meter with the figure beside its label, nothing under it. */
  orientation?: 'vertical' | 'horizontal'
}

const half = (v: number | null): number => Math.abs(v ?? 0) * 50

function Figure({ label, counts }: { label: string; counts: Counts }) {
  const net = netOf(counts)
  return (
    <div className="gauge__so">
      <span className="gauge__so-label mono">{label}</span>
      <b className="gauge__so-net" style={netStyle(net)}>
        {fmtNet(net)}
      </b>
      <SentimentBar counts={counts} size="mini" subject={label} />
      <small className="mono">{counts.total ? `of ${fmtInt(counts.total)} comments` : 'nothing yet'}</small>
    </div>
  )
}

export function NetGauge({ now, window, soFar, season, orientation = 'vertical' }: NetGaugeProps) {
  const net = netOf(now)
  const usual = netOf(season)
  const text = net === null ? 'Nothing about him yet.' : `Right now, net ${fmtNet(net)} over his last ${fmtInt(now.total)} comments: ${now.neg} negative, ${now.neu} neutral, ${now.pos} positive.`
  if (orientation === 'horizontal') {
    const fill = { '--gauge-l': `${net !== null && net < 0 ? 50 - half(net) : 50}%`, '--gauge-w': `${half(net)}%`, ...netFill(net) } as CSSProperties
    return (
      <div className="meter" role="img" aria-label={text}>
        <div className="meter__row mono">
          <span>
            The room on him · <b>right now</b>
          </span>
          <b style={netStyle(net)}>{net === null ? '' : `${fmtNet(net)} net`}</b>
        </div>
        <div className="meter__track">
          <span className="meter__zero" />
          {usual !== null && <span className="meter__usual" style={{ left: `${50 + usual * 50}%` }} />}
          {net !== null && <span className="meter__fill" style={fill} />}
        </div>
      </div>
    )
  }
  const fill = { '--gauge-t': `${net !== null && net > 0 ? 50 - half(net) : 50}%`, '--gauge-h': `${half(net)}%`, ...netFill(net) } as CSSProperties
  return (
    <aside className="gauge replay__panel" aria-label="The room on him, right now">
      <div className="replay__ph">
        <b>Right now</b>
        <span>his last {fmtInt(window)}</span>
      </div>
      <div className="gauge__body">
        <div className="gauge__track" aria-hidden="true">
          <span className="gauge__lab gauge__lab--top mono">+100</span>
          <span className="gauge__zero" />
          {usual !== null && <span className="gauge__usual" style={{ top: `${50 - usual * 50}%` }} />}
          {net !== null && <span className="gauge__fill" style={fill} />}
          <span className="gauge__lab gauge__lab--bot mono">−100</span>
        </div>
        <div className="gauge__read">
          <div className="gauge__num" style={netStyle(net)} aria-hidden="true">
            {fmtNet(net)}
          </div>
          <div className="gauge__sub mono" aria-hidden="true">
            net sentiment
            <br />
            about him
          </div>
          <div className="gauge__counts mono" aria-hidden="true">
            {now.total ? `${now.neg} neg · ${now.neu} neu · ${now.pos} pos` : 'nothing yet'}
          </div>
          <span className="visually-hidden">{text}</span>
          <Figure label="So far" counts={soFar} />
          <Figure label="His season" counts={season} />
        </div>
      </div>
    </aside>
  )
}
