// The Recap chip: a mono link to a game's recap with a play glyph. It sits
// at a games-table row's end and beside a loud thread's score; the context
// places it, the chip only looks like itself.

export interface RecapChipProps {
  href: string
  /** "Recap", or "Recap · Fox" where a game has more than one. */
  label?: string
}

export function RecapChip({ href, label = 'Recap' }: RecapChipProps) {
  return (
    <a className="chip" href={href}>
      <svg className="chip__glyph" viewBox="0 0 10 10" aria-hidden="true">
        <path d="M1 0l9 5-9 5z" />
      </svg>
      {label}
    </a>
  )
}
