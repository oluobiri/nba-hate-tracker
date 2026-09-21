export interface StatFigureProps {
  figure: string
  label: string
  detail?: string
  /** Colour only when the figure is a sentiment. */
  tone?: 'neg' | 'neu' | 'pos'
}

/** One number with its label and a quiet line of detail. */
export function StatFigure({ figure, label, detail, tone }: StatFigureProps) {
  return (
    <div className={`stat${tone ? ` stat--${tone}` : ''}`}>
      <span className="stat__figure">{figure}</span>
      <span className="stat__label">{label}</span>
      {detail && <span className="stat__detail">{detail}</span>}
    </div>
  )
}
