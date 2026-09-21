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
  children: ReactNode
}

/** The yellow box. Method only: threshold, rules, caveats, how a number was made. */
export function MethodNote({ kind, children }: MethodNoteProps) {
  return (
    <aside className={`note note--${kind}`}>
      <span className="note__eyebrow">{EYEBROW[kind]}</span>
      <div className="note__body">{children}</div>
    </aside>
  )
}
