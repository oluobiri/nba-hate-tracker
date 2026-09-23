// The receipts: one island. Three tabs in sentiment order, the tab and the
// expansion in the URL, so a link opens on the same receipts. Verified
// stamps on negative and positive only; never a username.
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { useLayoutEffect, useMemo, useRef, type KeyboardEvent } from 'react'

import '../styles/receipts.css'
import { fmtInt } from '../lib/format'
import type { ReceiptContext } from '../lib/receipts'
import { SENTIMENTS, type Sentiment } from '../lib/types'
import { useViewState } from '../lib/url'
import { Exhibit } from './Exhibit'

export interface ReceiptItem {
  body: string
  score: number
  sourceUrl: string
  context: ReceiptContext | null
  flair: string | null
  date: string
}

export interface ReceiptsProps {
  name: string
  cells: Record<Sentiment, ReceiptItem[]>
  /** rules.receipts.verified: the stamp on negative and positive receipts. */
  verified: boolean
  /** How many show before "Show all": a page choice. */
  top: number
  /** rules.qualified_threshold, the view state's one default. */
  official: number
}

const LABEL: Record<Sentiment, string> = { neg: 'Negative', neu: 'Neutral', pos: 'Positive' }
const WORD: Record<Sentiment, string> = { neg: 'negative', neu: 'neutral', pos: 'positive' }

export function Receipts({ name, cells, verified, top, official }: ReceiptsProps) {
  const defaults = useMemo(() => ({ threshold: official }), [official])
  const [view, update, ready] = useViewState(defaults)
  const { tab, all } = view

  // A deep link's prerendered default stays hidden until the URL is in.
  useLayoutEffect(() => {
    if (ready) document.documentElement.classList.remove('has-receipts-view')
  }, [ready])

  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const move = (to: number) => {
    const next = SENTIMENTS[(to + SENTIMENTS.length) % SENTIMENTS.length]!
    update({ tab: next })
    refs.current[SENTIMENTS.indexOf(next)]?.focus()
  }
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const keys: Record<string, () => void> = {
      ArrowRight: () => move(i + 1),
      ArrowLeft: () => move(i - 1),
      Home: () => move(0),
      End: () => move(SENTIMENTS.length - 1),
    }
    const go = keys[e.key]
    if (go) {
      e.preventDefault()
      go()
    }
  }

  const items = cells[tab]
  const shown = all ? items : items.slice(0, top)
  const fade = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: -6 }, transition: { duration: 0.18 } }

  return (
    <MotionConfig reducedMotion="user">
      <div className="rc">
        <div className="tabs">
          <div className="tabs__list" role="tablist" aria-label="Receipts by sentiment">
            {SENTIMENTS.map((s, i) => (
              <button
                key={s}
                ref={(el) => {
                  refs.current[i] = el
                }}
                id={`rc-tab-${s}`}
                className={`tabs__tab tabs__tab--${s}`}
                role="tab"
                type="button"
                aria-selected={s === tab}
                aria-controls="rc-panel"
                tabIndex={s === tab ? 0 : -1}
                onClick={() => update({ tab: s })}
                onKeyDown={(e) => onKeyDown(e, i)}
              >
                {LABEL[s]} <span className="tabs__count mono">{cells[s].length}</span>
                {s === tab && <motion.span className="tabs__line" layoutId="rc-line" transition={{ type: 'spring', stiffness: 400, damping: 40 }} />}
              </button>
            ))}
          </div>
        </div>
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={tab} id="rc-panel" role="tabpanel" aria-labelledby={`rc-tab-${tab}`} className="rc__panel" {...fade}>
            {items.length === 0 ? (
              <p className="rc__empty">No {WORD[tab]} receipt about {name} cleared the bar this season.</p>
            ) : (
              <ol className="rc__list">
                {shown.map((r, i) => (
                  <li key={r.sourceUrl}>
                    <Exhibit
                      number={i + 1}
                      body={r.body}
                      sentiment={tab}
                      score={r.score}
                      sourceUrl={r.sourceUrl}
                      context={r.context}
                      flair={r.flair}
                      date={r.date}
                      stamp={verified && tab !== 'neu' ? 'verified' : undefined}
                    />
                  </li>
                ))}
              </ol>
            )}
            {items.length > top && (
              <div className="rc__foot">
                <button type="button" className="btn" onClick={() => update({ all: !all })}>
                  {all ? `Show ${top}` : `Show all ${fmtInt(items.length)}`}
                </button>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </MotionConfig>
  )
}
