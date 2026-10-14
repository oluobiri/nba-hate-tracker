export type StampKind = 'unofficial'

const TEXT: Record<StampKind, string> = { unofficial: 'Unofficial' }

/** A method mark on a view: the leaderboard below the official minimum. */
export function Stamp({ kind }: { kind: StampKind }) {
  return <span className={`stamp stamp--${kind}`}>{TEXT[kind]}</span>
}
