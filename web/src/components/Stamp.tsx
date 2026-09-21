export type StampKind = 'verified' | 'unofficial'

const TEXT: Record<StampKind, string> = { verified: 'Verified', unofficial: 'Unofficial' }

/** A method mark on a receipt or a view. */
export function Stamp({ kind }: { kind: StampKind }) {
  return <span className={`stamp stamp--${kind}`}>{TEXT[kind]}</span>
}
