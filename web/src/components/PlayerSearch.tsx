// The header search: a WAI-ARIA combobox over every tracked player. The
// first island, and the only JavaScript a static page carries.
import { useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'

export interface SearchPlayer {
  name: string
  slug: string
  abbr: string | null
}

const MAX_RESULTS = 8

const go = (slug: string) => {
  window.location.assign(`/player/${slug}/`)
}

const fold = (s: string): string =>
  s
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()

export function PlayerSearch({ players }: { players: SearchPlayer[] }) {
  const id = useId()
  const listId = `${id}-list`
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)

  const indexed = useMemo(() => players.map((p) => ({ ...p, key: fold(p.name) })), [players])
  const results = useMemo(() => {
    const q = fold(query.trim())
    if (!q) return []
    const starts = indexed.filter((p) => p.key.startsWith(q))
    const within = indexed.filter((p) => !p.key.startsWith(q) && p.key.includes(q))
    return [...starts, ...within].slice(0, MAX_RESULTS)
  }, [indexed, query])

  const expanded = open && results.length > 0

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setOpen(true)
        setActive((i) => Math.min(i + 1, results.length - 1))
        break
      case 'ArrowUp':
        e.preventDefault()
        setOpen(true)
        setActive((i) => Math.max(i - 1, 0))
        break
      case 'Home':
        if (expanded) {
          e.preventDefault()
          setActive(0)
        }
        break
      case 'End':
        if (expanded) {
          e.preventDefault()
          setActive(results.length - 1)
        }
        break
      case 'Enter': {
        const hit = results[active]
        if (expanded && hit) {
          e.preventDefault()
          go(hit.slug)
        }
        break
      }
      case 'Escape':
        if (expanded) {
          e.preventDefault()
          setOpen(false)
        } else if (query) {
          setQuery('')
        }
        break
      default:
    }
  }

  return (
    <div className="search">
      <label className="visually-hidden" htmlFor={`${id}-input`}>
        Search players
      </label>
      <input
        ref={inputRef}
        id={`${id}-input`}
        className="search__input"
        type="text"
        role="combobox"
        placeholder="Search players"
        autoComplete="off"
        spellCheck={false}
        aria-expanded={expanded}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={expanded ? `${listId}-${active}` : undefined}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value)
          setActive(0)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      <ul id={listId} className="search__list" role="listbox" aria-label="Players" hidden={!expanded}>
        {results.map((p, i) => (
          <li
            key={p.slug}
            id={`${listId}-${i}`}
            role="option"
            aria-selected={i === active}
            className={`search__option${i === active ? ' search__option--active' : ''}`}
            onMouseDown={(e) => e.preventDefault()}
            onMouseEnter={() => setActive(i)}
            onClick={() => go(p.slug)}
          >
            <span>{p.name}</span>
            <span className="search__abbr">{p.abbr ?? '—'}</span>
          </li>
        ))}
      </ul>
      <div className="visually-hidden" role="status" aria-live="polite">
        {query.trim() ? `${results.length} player${results.length === 1 ? '' : 's'} found` : ''}
      </div>
    </div>
  )
}
