export interface RankNumeralProps {
  rank: number
  /** False below the official minimum: the numeral is drawn hollow. */
  official: boolean
  size?: 'md' | 'lg'
}

/** A rank that looks different when it is not the official one, even in a tight crop. */
export function RankNumeral({ rank, official, size = 'md' }: RankNumeralProps) {
  return (
    <span className={`rank rank--${size}${official ? '' : ' rank--hollow'}`}>
      {rank}
      {!official && <span className="visually-hidden"> (unofficial)</span>}
    </span>
  )
}
