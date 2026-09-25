// The boards, computed once per build and shared by a page and its share
// card, so a rank or a verdict is never derived twice. The official board
// numbers players at or above the manifest's minimum; the all-players board
// numbers everyone tracked. Fanbases are all ranked, there is no minimum.
import type { FanTeamOverallRow, PlayerOverallRow, PlayersRow } from '../data/types.gen'
import type { VerdictInput } from './annotate'
import { countsOf, rankBy, type Ranked, sumCounts } from './metrics'
import { type Counts, LENSES, type Lens } from './types'

export interface Standing extends Counts {
  name: string
  slug: string
}

export interface PlayerStandings {
  /** Every player with comments, unsorted. */
  overall: Standing[]
  /** The official board per lens. */
  rankings: Record<Lens, Ranked<Standing>[]>
  /** Every tracked player per lens, no minimum. */
  allRankings: Record<Lens, Ranked<Standing>[]>
  /** The room's own counts: every official player summed. */
  league: Counts
  /** One verdict input per tracked player, zero counts when he drew no comments. */
  inputs: Map<string, VerdictInput>
}

const ZERO: Counts = { neg: 0, neu: 0, pos: 0, total: 0 }

/** A player's rank on a board; null when he is unranked or absent. */
export const rankIn = (rs: readonly Ranked<Standing>[], name: string): number | null => rs.find((r) => r.row.name === name)?.rank ?? null

const perLens = <T>(f: (lens: Lens) => T): Record<Lens, T> => Object.fromEntries(LENSES.map((l) => [l, f(l)])) as Record<Lens, T>

/** Both boards and every player's verdict input, from the two dimension tables. */
export function playerStandings(
  tables: { players: readonly PlayersRow[]; player_overall: readonly PlayerOverallRow[] },
  official: number,
): PlayerStandings {
  const dim = new Map(tables.players.map((p) => [p.attributed_player, p]))
  const overall: Standing[] = tables.player_overall.map((r) => ({ ...countsOf(r), name: r.attributed_player, slug: dim.get(r.attributed_player)!.slug }))
  const overallBy = new Map(overall.map((r) => [r.name, r]))
  const rankings = perLens((l) => rankBy(overall, l, official))
  const allRankings = perLens((l) => rankBy(overall, l, 0))
  const league = sumCounts(overall.filter((r) => r.total >= official))
  const tracked = overall.length
  const inputs = new Map(
    tables.players.map((p) => {
      const name = p.attributed_player
      const row = overallBy.get(name)
      const counts: Counts = row ? { neg: row.neg, neu: row.neu, pos: row.pos, total: row.total } : ZERO
      const ranks = perLens((l) => rankIn(rankings[l], name))
      const allRanks = perLens((l) => rankIn(allRankings[l], name) ?? tracked)
      return [name, { name, counts, official, ranks, allRanks, tracked, league } satisfies VerdictInput]
    }),
  )
  return { overall, rankings, allRankings, league, inputs }
}

export type TeamRow = Counts & { team: FanTeamOverallRow }

/** Every fanbase ranked by negative rate; rank 1 is the saltiest. */
export function fanbaseStandings(rows: readonly FanTeamOverallRow[]): Ranked<TeamRow>[] {
  return rankBy(
    rows.map((r) => ({ ...countsOf(r), team: r })),
    'neg',
    0,
  )
}
