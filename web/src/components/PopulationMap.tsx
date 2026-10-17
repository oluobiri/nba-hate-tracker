// Who gets talked about: one island. Every tracked player as a tile sized
// by his comments and coloured by net on the player rule, grouped by roster
// team; the official toggle, the conference select and the zoom are local
// state, nothing a link carries. The build lays the map at the content
// width; the island measures its box and lays it again. HTML tiles, since
// they hold text and, zoomed, the link to his page.
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from 'motion/react'
import { type CSSProperties, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import '../styles/population.css'
import { fmtInt } from '../lib/format'
import { fmtNet, netOf, type PlayerNetRange, playerNetColor } from '../lib/net'
import { type Conf, CONFERENCES, headerLabel, headerText, layoutMap, NO_ROSTER_NAME, officialCount, type PopulationRow, populationView, type Scope, showNet, tileBase, tileLabel, tileText } from '../lib/population'
import { MethodNote } from './MethodNote'

export interface PopulationMapProps {
  rows: PopulationRow[]
  /** rules.qualified_threshold */
  official: number
  /** The season's player extremes, the tiles' colour scale. */
  netRange: PlayerNetRange
  /** Style guide only: a fixed width and view, never measured. */
  demo?: { width: number; scope?: Scope; conf?: Conf; zoom?: string | null }
}

// Page choices, not rules: the width the build lays the map at (the content
// max), the map's height by its width, and a zoom's travel time.
const SSR_WIDTH = 1180
const TALL_UNDER = 560
const TALL_RATIO = 1.35
const WIDE_RATIO = 0.6
const H_MIN = 480
const H_MAX = 760
const TRAVEL_S = 0.35

const mapHeight = (w: number): number => Math.round(w < TALL_UNDER ? w * TALL_RATIO : Math.max(H_MIN, Math.min(H_MAX, w * WIDE_RATIO)))

const SCOPES: readonly { key: Scope; label: (tracked: number, official: number) => string }[] = [
  { key: 'all', label: (tracked) => `All ${fmtInt(tracked)}` },
  { key: 'official', label: (_, official) => `Official ${fmtInt(official)}` },
]

export function PopulationMap({ rows, official, netRange, demo }: PopulationMapProps) {
  const [scope, setScope] = useState<Scope>(demo?.scope ?? 'all')
  const [conf, setConf] = useState<Conf>(demo?.conf ?? 'all')
  const [zoom, setZoom] = useState<string | null>(demo?.zoom ?? null)
  const [width, setWidth] = useState(demo?.width ?? SSR_WIDTH)
  const box = useRef<HTMLDivElement>(null)
  const back = useRef<HTMLButtonElement>(null)
  const reduce = useReducedMotion()
  const travel = reduce ? 0 : TRAVEL_S

  // The box's width, before the first client paint and on every resize.
  useLayoutEffect(() => {
    const el = box.current
    if (demo || !el) return
    const measure = () => {
      const w = Math.round(el.clientWidth)
      if (w > 0) setWidth((prev) => (Math.abs(prev - w) < 2 ? prev : w))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [demo])

  // After a zoom, focus lands on Back; after Back, on the header of the team just left, or the first.
  const moved = useRef<string | null>(null)
  const left = useRef<string | null>(null)
  useEffect(() => {
    if (moved.current === null) return
    const from = moved.current
    moved.current = null
    if (zoom) back.current?.focus()
    else (box.current?.querySelector<HTMLElement>(`.pm__group[data-key="${CSS.escape(from)}"]`) ?? box.current?.querySelector<HTMLElement>('.pm__group'))?.focus()
  }, [zoom])
  const go = (key: string | null): void => {
    moved.current = key ?? left.current ?? ''
    left.current = key
    setZoom(key)
  }
  // A view that cannot hold the zoomed team (the toggle emptied it, the conference changed) shows the whole map.
  const pick = (next: { scope?: Scope; conf?: Conf }): void => {
    const s = next.scope ?? scope
    const c = next.conf ?? conf
    if (zoom !== null && populationView(rows, { scope: s, conf: c, zoom, official }).zoomed === null) setZoom(null)
    if (next.scope) setScope(next.scope)
    if (next.conf) setConf(next.conf)
  }

  const view = useMemo(() => populationView(rows, { scope, conf, zoom, official }), [rows, scope, conf, zoom, official])
  const height = mapHeight(width)
  const layout = useMemo(() => layoutMap(view, width, height), [view, width, height])
  const tracked = rows.length
  const officialN = officialCount(rows, official)
  const noRoster = rows.filter((r) => r.abbr === null).length
  const zoomed = view.zoomed !== null

  return (
    <MotionConfig reducedMotion="user">
      <section className="pm" aria-labelledby="pop-h">
        <header className="pm__head">
          <p className="eyebrow">{view.eyebrow}</p>
          <h2 id="pop-h">Who gets talked about?</h2>
        </header>

        <div className="pm__controls">
          <div className="pm__toggle" role="group" aria-label="Players">
            {SCOPES.map((s) => (
              <button key={s.key} type="button" className="btn" aria-pressed={s.key === scope} onClick={() => pick({ scope: s.key })}>
                {s.label(tracked, officialN)}
              </button>
            ))}
          </div>
          <ul className="key">
            <li>
              <i className="key__dot key__dot--late" /> Each box is a player, sized by comments and coloured by net sentiment
            </li>
          </ul>
        </div>

        <div className="pm__crumb mono">
          <select
            className="pm__select"
            aria-label="Conference"
            value={conf}
            onChange={(e) => pick({ conf: e.target.value as Conf })}
          >
            {CONFERENCES.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
          {zoomed ? (
            <>
              <span aria-hidden="true">›</span>
              <span className="pm__team">{view.crumb}</span>
              <button ref={back} type="button" className="pm__back" onClick={() => go(null)}>
                Back
              </button>
            </>
          ) : (
            <span>{view.crumb}</span>
          )}
        </div>

        <div ref={box} className="pm__map" style={{ height }}>
          {layout.headers.map((h) => {
            const { title, detail } = headerLabel(h.group, h.w)
            return (
              <button
                key={h.group.key}
                type="button"
                className="pm__group"
                data-key={h.group.key}
                style={{ left: h.x, top: h.y, width: h.w, height: h.h }}
                aria-label={headerText(h.group)}
                title={headerText(h.group)}
                onClick={() => go(h.group.key)}
              >
                {h.group.logo && <span className="pm__logo" aria-hidden="true" style={{ backgroundImage: `url(${h.group.logo})` }} />}
                <span className="pm__abbr">{title}</span>
                {detail && <span>{detail}</span>}
              </button>
            )
          })}
          <AnimatePresence initial={false}>
            {layout.tiles.map((t) => {
              const net = netOf(t.row)
              const label = tileLabel(t.row.name, t.w, t.h, tileBase(t.w, t.h))
              const netLine = label !== null && (zoomed || showNet(label, t.w, t.h))
              const text = tileText(t.row)
              const geometry = { left: t.x, top: t.y, width: t.w, height: t.h }
              const body = (
                <span className="pm__text">
                  {label && (
                    <span className="pm__name" style={{ fontSize: label.fontSize }} aria-hidden="true">
                      <span>{label.line1}</span>
                      {label.line2 && <span>{label.line2}</span>}
                    </span>
                  )}
                  {netLine && (
                    <span className="pm__net mono" aria-hidden="true">
                      {fmtNet(net)} net
                    </span>
                  )}
                </span>
              )
              return (
                <motion.div
                  key={t.row.slug}
                  className="pm__box"
                  data-key={t.group.key}
                  style={{ '--fill': playerNetColor(net, netRange) } as CSSProperties}
                  initial={{ opacity: 0, ...geometry }}
                  animate={{ opacity: 1, ...geometry }}
                  exit={{ opacity: 0, pointerEvents: 'none' }}
                  transition={{ duration: travel }}
                >
                  {zoomed ? (
                    <a className="pm__tile" href={`/player/${t.row.slug}/`} aria-label={text} title={text}>
                      {body}
                    </a>
                  ) : (
                    <button type="button" className="pm__tile" aria-label={text} title={text} tabIndex={-1} onClick={() => go(t.group.key)}>
                      {body}
                    </button>
                  )}
                </motion.div>
              )
            })}
          </AnimatePresence>
        </div>

        <MethodNote kind="method">
          Each box is one player; its area is the comments attributed to him. Its fill is net sentiment, the positive share minus the negative, on the player rule: full heat
          at the season's lowest player, full ice at its highest, bone at zero, over every tracked player, so a shade means the same net in every view here and on every
          player page. Official keeps the players at the minimum of {fmtInt(official)} comments. A team is the roster the site lists beside each name, its header summed over
          the boxes shown; the {fmtInt(noRoster)} players without a roster team at season end sit together under "{NO_ROSTER_NAME}" and appear only under All teams.
          The counts are the population's: a player too small to draw at this width is counted, not drawn.
        </MethodNote>
      </section>
    </MotionConfig>
  )
}
