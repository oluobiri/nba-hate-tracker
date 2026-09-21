// Shapes shared by every sentiment surface. Rates are never stored on
// these; they are derived from counts (see metrics.ts).

export type Lens = 'neg' | 'pos' | 'volume' | 'polar'
export const LENSES: readonly Lens[] = ['neg', 'pos', 'volume', 'polar']

export type Sentiment = 'neg' | 'neu' | 'pos'
// Display order everywhere: negative → neutral → positive.
export const SENTIMENTS: readonly Sentiment[] = ['neg', 'neu', 'pos']

export interface Counts {
  neg: number
  neu: number
  pos: number
  total: number
}
