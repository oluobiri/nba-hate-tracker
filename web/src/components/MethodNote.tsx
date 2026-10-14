import type { ReactNode } from 'react'

export type NoteKind = 'read-first' | 'rule' | 'caveat' | 'method'

const EYEBROW: Record<NoteKind, string> = {
  'read-first': 'Read this first',
  rule: 'Rule',
  caveat: 'Caveat',
  method: 'Method',
}

export interface MethodNoteProps {
  kind: NoteKind
  /** A method note starts open (the style guide's open variant); the other kinds are always open. */
  open?: boolean
  children: ReactNode
}

/**
 * The yellow box. Method only: threshold, rules, caveats, how a number was made.
 * A rule, a caveat and a read-first are claims the reader needs, so they stay open; a
 * method note is provenance, so it folds to its eyebrow, a native details with no script.
 */
export function MethodNote({ kind, open = false, children }: MethodNoteProps) {
  if (kind === 'method') {
    return (
      <details className="note note--method" open={open}>
        <summary className="note__eyebrow">{EYEBROW[kind]}</summary>
        <div className="note__body">{children}</div>
      </details>
    )
  }
  return (
    <aside className={`note note--${kind}`}>
      <span className="note__eyebrow">{EYEBROW[kind]}</span>
      <div className="note__body">{children}</div>
    </aside>
  )
}
