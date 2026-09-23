// The four lenses as a tablist. The underline is the lens's colour job:
// heat, ice, bone, and split heat-ice for polarization.
import { motion } from 'motion/react'
import { useRef, type KeyboardEvent } from 'react'

import { LENS_META } from '../lib/metrics'
import { LENSES, type Lens } from '../lib/types'

export interface LensTabsProps {
  lens: Lens
  onChange: (lens: Lens) => void
  /** Prefix for the tab and panel ids, so several tablists can share a page. */
  id?: string
}

/** Lens switcher: arrow keys move, Home/End jump, the subtitle names the metric. */
export function LensTabs({ lens, onChange, id = 'lens' }: LensTabsProps) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])

  const move = (to: number) => {
    const next = LENSES[(to + LENSES.length) % LENSES.length]!
    onChange(next)
    refs.current[LENSES.indexOf(next)]?.focus()
  }

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    switch (e.key) {
      case 'ArrowRight':
        e.preventDefault()
        move(i + 1)
        break
      case 'ArrowLeft':
        e.preventDefault()
        move(i - 1)
        break
      case 'Home':
        e.preventDefault()
        move(0)
        break
      case 'End':
        e.preventDefault()
        move(LENSES.length - 1)
        break
      default:
    }
  }

  return (
    <div className="tabs">
      <div className="tabs__list" role="tablist" aria-label="Lens">
        {LENSES.map((l, i) => (
          <button
            key={l}
            ref={(el) => {
              refs.current[i] = el
            }}
            id={`${id}-tab-${l}`}
            className={`tabs__tab tabs__tab--${l}`}
            role="tab"
            type="button"
            aria-selected={l === lens}
            aria-controls={`${id}-panel`}
            tabIndex={l === lens ? 0 : -1}
            onClick={() => onChange(l)}
            onKeyDown={(e) => onKeyDown(e, i)}
          >
            {LENS_META[l].label}
            {l === lens && <motion.span className="tabs__line" layoutId={`${id}-line`} transition={{ type: 'spring', stiffness: 400, damping: 40 }} />}
          </button>
        ))}
      </div>
      <p className="tabs__unit mono">{LENS_META[lens].unit}</p>
    </div>
  )
}
