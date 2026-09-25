// What a share card says, derived from the same inputs as the page it
// stands for: the sentence is the page header's sentence, the view is the
// official one, and no receipt text ever reaches a card.
import type { FanTeamOverallRow, PlayersRow } from '../data/types.gen'
import { heroSentence, playerVerdict, type VerdictInput } from '../lib/annotate'
import { fanbaseVerdict } from '../lib/fanbase'
import { possessive } from '../lib/fans'
import { fmtInt, fmtPct } from '../lib/format'
import { negRate, neuRate, posRate, type Ranked } from '../lib/metrics'
import type { Standing } from '../lib/standings'
import { type Counts, SENTIMENTS, type Sentiment } from '../lib/types'

// The card's inner width, and the narrowest hero segment that holds its own label.
export const CARD_PAD = 48
export const BAR_WIDTH = 1200 - 2 * CARD_PAD
export const LABEL_MIN = 56

const NAMES: Record<Sentiment, string> = { neg: 'negative', neu: 'neutral', pos: 'positive' }
const RATES: Record<Sentiment, (c: Counts) => number> = { neg: negRate, neu: neuRate, pos: posRate }

export interface Segment {
  key: Sentiment
  share: number
  /** "51.0%", drawn inside the segment when it fits. */
  label: string
  labelFits: boolean
  /** "51.0% negative", drawn under the bar otherwise. */
  under: string
}

export type Stamp = 'unofficial' | null

interface CardBase {
  season: string
  /** The page header's sentence, verbatim. */
  sentence: string
  segments: Segment[]
  nLine: string
  stamp: Stamp
  /** First-party media, fetched at build. */
  image: string
}

export interface PlayerCard extends CardBase {
  kind: 'player'
  name: string
  /** "GSW · F · #23", or "Free agent". */
  eyebrow: string
}

export interface TeamCard extends CardBase {
  kind: 'team'
  /** "Lakers fans". */
  title: string
  /** "LAL · West". */
  eyebrow: string
}

export interface BoardCard extends CardBase {
  kind: 'board'
  name: string
  /** "1,234,567 comments about 223 players". */
  kicker: string
}

export type Card = PlayerCard | TeamCard | BoardCard

/** The hero bar's segments, negative → neutral → positive, labels placed by the same width rule as the CSS. */
export function barSegments(counts: Counts, width: number = BAR_WIDTH): Segment[] {
  return SENTIMENTS.map((key) => {
    const share = RATES[key](counts)
    return { key, share, label: fmtPct(share), labelFits: share * width >= LABEL_MIN, under: `${fmtPct(share)} ${NAMES[key]}` }
  })
}

/** Under the name: team · position · number, as a sports page reads; "Free agent" without a roster team. */
export const idLine = (player: Pick<PlayersRow, 'roster_team' | 'position' | 'jersey_number'>, rosterAbbr: string | null): string =>
  player.roster_team ? [rosterAbbr, player.position, player.jersey_number ? `#${player.jersey_number}` : null].filter(Boolean).join(' · ') : 'Free agent'

export function playerCard(input: VerdictInput, player: PlayersRow, rosterAbbr: string | null, season: string): PlayerCard {
  return {
    kind: 'player',
    season,
    name: input.name,
    eyebrow: idLine(player, rosterAbbr),
    sentence: playerVerdict(input).sentence,
    segments: barSegments(input.counts),
    nLine: `n=${fmtInt(input.counts.total)} comments about ${input.name}`,
    stamp: input.ranks.neg === null ? 'unofficial' : null,
    image: player.headshot_url,
  }
}

export function teamCard(team: FanTeamOverallRow, counts: Counts, rank: number, of: number, season: string): TeamCard {
  const fans = possessive(team.fan_team)
  return {
    kind: 'team',
    season,
    title: fans,
    eyebrow: `${team.abbreviation} · ${team.conference}`,
    sentence: fanbaseVerdict(team.fan_team, counts, { rank, of }),
    segments: barSegments(counts),
    nLine: `n=${fmtInt(counts.total)} comments by ${fans} about tracked players`,
    stamp: null,
    image: team.logo_url,
  }
}

export interface Headline {
  count: number
  players: number
}

/** The leaderboard's card: the official #1 by negative rate with the hero sentence. */
export function boardCard(ranked: readonly Ranked<Standing>[], official: number, headline: Headline, headshotOf: (name: string) => string, season: string): BoardCard {
  const leader = ranked.find((r) => r.rank !== null)
  if (!leader) throw new Error(`no player reaches the official minimum of ${official}; the leaderboard has no card`)
  return {
    kind: 'board',
    season,
    name: leader.row.name,
    kicker: `${fmtInt(headline.count)} comments about ${fmtInt(headline.players)} players`,
    sentence: heroSentence({ ranked, lens: 'neg', threshold: official, official }),
    segments: barSegments(leader.row),
    nLine: `n=${fmtInt(leader.row.total)} comments about ${leader.row.name}`,
    stamp: null,
    image: headshotOf(leader.row.name),
  }
}

/** Where each card lives, so pages and endpoints agree. */
export const cardHref = {
  player: (slug: string): string => `/player/${slug}/card.png`,
  team: (abbreviation: string): string => `/fanbases/${abbreviation.toLowerCase()}/card.png`,
  board: '/card.png',
} as const
