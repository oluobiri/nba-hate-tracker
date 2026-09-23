// "Read this first": the sentences that put the framing inside the visual.
// Every figure is computed from the ranked rows; the thresholds arrive as
// arguments. The output doubles as the board's text alternative.
import { fmtInt, fmtPct, ordinal } from './format'
import { LENS_META, negRate, polarization, posRate, rankBy, type Ranked } from './metrics'
import type { Counts, Lens } from './types'

export interface Named extends Counts {
  name: string
}

export interface AnnotateInput<T extends Named> {
  /** The board as ranked for the current lens and threshold. */
  ranked: readonly Ranked<T>[]
  lens: Lens
  threshold: number
  official: number
}

const plural = (n: number, one: string, many: string): string => (n === 1 ? one : many)

const rankWord = (rank: number | null): string => (rank === null ? 'is not ranked at this minimum' : `ranks ${ordinal(rank)} here`)

function rateLens<T extends Named>(ranked: readonly Ranked<T>[], lens: 'neg' | 'pos'): string[] {
  const leader = ranked.find((r) => r.rank !== null)
  if (!leader) return ['No player reaches this minimum.']
  const rate = lens === 'neg' ? negRate : posRate
  const word = lens === 'neg' ? 'negative' : 'positive'
  const loudest = ranked.reduce((a, b) => (b.row.total > a.row.total ? b : a))
  const first = `Rates, not volume: ${fmtPct(rate(leader.row))} of the ${fmtInt(leader.row.total)} comments about ${leader.row.name} are ${word}.`
  if (loudest === leader) return [first, `${leader.row.name} is also the most discussed player on the board.`]
  const times = loudest.row.total / leader.row.total
  const second = `The most discussed player, ${loudest.row.name}, draws ${times.toFixed(1)}× the comments at ${fmtPct(rate(loudest.row))} ${word} and ${rankWord(loudest.rank)}.`
  return [first, second]
}

function volumeLens<T extends Named>(ranked: readonly Ranked<T>[], threshold: number): string[] {
  const leader = ranked.find((r) => r.rank !== null)
  if (!leader) return ['No player reaches this minimum.']
  const byNeg = rankBy(
    ranked.map((r) => r.row),
    'neg',
    threshold,
  )
  const negRank = byNeg.find((r) => r.row === leader.row)?.rank ?? null
  return [
    `Volume is not hate: ${leader.row.name} is the most discussed player at ${fmtInt(leader.row.total)} comments, ${fmtPct(negRate(leader.row))} of them negative, which ${rankWord(negRank).replace('here', 'by negative rate')}.`,
  ]
}

function polarLens<T extends Named>(ranked: readonly Ranked<T>[]): string[] {
  const leader = ranked.find((r) => r.rank !== null)
  if (!leader) return ['No player reaches this minimum.']
  return [
    `Polarization is the share of comments that take a side, negative or positive; neutral does not count.`,
    `${leader.row.name} leads at ${fmtPct(polarization(leader.row))}: ${fmtPct(negRate(leader.row))} negative, ${fmtPct(posRate(leader.row))} positive.`,
  ]
}

function customView<T extends Named>(ranked: readonly Ranked<T>[], threshold: number, official: number): string[] {
  if (threshold === official) return []
  const rankedRows = ranked.filter((r) => r.rank !== null)
  if (threshold < official) {
    const below = rankedRows.filter((r) => r.row.total < official).length
    return [
      `Unofficial view: minimum ${fmtInt(threshold)} comments. ${fmtInt(below)} of the ${fmtInt(rankedRows.length)} ranked players ${plural(below, 'sits', 'sit')} below the official minimum of ${fmtInt(official)}; ${plural(below, 'its rank is', 'their ranks are')} drawn hollow.`,
    ]
  }
  return [`Custom view: minimum ${fmtInt(threshold)} comments, above the official ${fmtInt(official)}. ${fmtInt(rankedRows.length)} ${plural(rankedRows.length, 'player qualifies', 'players qualify')}.`]
}

/** The sentences for the current view, lens first, then the custom-threshold note. */
export function annotate<T extends Named>({ ranked, lens, threshold, official }: AnnotateInput<T>): string[] {
  const body =
    lens === 'neg' || lens === 'pos' ? rateLens(ranked, lens) : lens === 'volume' ? volumeLens(ranked, threshold) : polarLens(ranked)
  return [...body, ...customView(ranked, threshold, official)]
}

export interface HeroParts<T extends Named> {
  before: string
  leader: Ranked<T> | null
  after: string
}

/** The hero sentence in parts, so the page can link the name: before · leader · after. */
export function heroParts<T extends Named>({ ranked, lens, threshold, official }: AnnotateInput<T>): HeroParts<T> {
  const leader = ranked.find((r) => r.rank !== null) ?? null
  if (!leader) return { before: `No player has ${fmtInt(threshold)} comments.`, leader, after: '' }
  const core = `r/NBA's ${LENS_META[lens].hero} player is `
  if (threshold === official) return { before: core, leader, after: '.' }
  return { before: `With at least ${fmtInt(threshold)} comments, ${core}`, leader, after: ' (unofficial).' }
}

/** The hero sentence as one string: "r/NBA's most hated player is …", per lens and threshold. */
export function heroSentence<T extends Named>(input: AnnotateInput<T>): string {
  const { before, leader, after } = heroParts(input)
  return `${before}${leader?.row.name ?? ''}${after}`
}
