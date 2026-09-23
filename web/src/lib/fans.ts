// The Fans section: how a player's own fans, rival fans and unflaired
// commenters talk about him, and which fanbases stand out. player_fan_team
// carries flaired comments only and applies no floor; the unflaired
// remainder is the player's overall counts minus the flaired sum.
import { fmtInt, fmtPct } from './format'
import { negRate, posRate, sumCounts } from './metrics'
import type { Counts } from './types'

export interface FanRow extends Counts {
  /** The fanbase's canonical team name. */
  team: string
}

export interface FanSplit {
  /** His own roster team's fans; null for a player with no roster team. */
  own: Counts | null
  /** Every other flaired fanbase, summed. */
  rivals: Counts
  /** Commenters with no flair: overall minus flaired, never negative. */
  unflaired: Counts
  /** Every flaired fanbase, summed. */
  flaired: Counts
}

const minus = (a: Counts, b: Counts): Counts => ({
  neg: Math.max(0, a.neg - b.neg),
  neu: Math.max(0, a.neu - b.neu),
  pos: Math.max(0, a.pos - b.pos),
  total: Math.max(0, a.total - b.total),
})

export function fanSplit(overall: Counts, rows: readonly FanRow[], rosterTeam: string | null): FanSplit {
  const flaired = sumCounts(rows)
  const ownRow = rosterTeam ? (rows.find((r) => r.team === rosterTeam) ?? null) : null
  const own = rosterTeam ? sumCounts(ownRow ? [ownRow] : []) : null
  return { own, rivals: own ? minus(flaired, own) : flaired, unflaired: minus(overall, flaired), flaired }
}

export interface FanListRow extends FanRow {
  own: boolean
}

export interface FanLists {
  /** Fanbases at the floor, most negative first. */
  haters: FanListRow[]
  /** Fanbases at the floor, most positive first. */
  defenders: FanListRow[]
  /** His rate across every flaired fanbase, from summed counts: the tick both lists sit against. */
  average: Counts
  /** How many fanbases reached the floor. */
  eligible: number
}

/** The two lists, each `limit` long, over fanbases with at least `floor` comments about him. */
export function fanLists(rows: readonly FanRow[], floor: number, rosterTeam: string | null, limit: number): FanLists {
  const eligible = rows.filter((r) => r.total >= floor).map((r) => ({ ...r, own: r.team === rosterTeam }))
  const by = (rate: (c: Counts) => number) => eligible.toSorted((a, b) => rate(b) - rate(a) || b.total - a.total).slice(0, limit)
  return { haters: by(negRate), defenders: by(posRate), average: sumCounts(rows), eligible: eligible.length }
}

const possessive = (team: string): string => `${team.split(' ').at(-1)} fans`

/** One sentence for the section: the split, then who stands out. */
export function fansSummary(name: string, split: FanSplit, lists: FanLists, floor: number, rosterTeam: string | null): string {
  const parts: string[] = []
  if (split.own && rosterTeam) parts.push(`his own ${possessive(rosterTeam)} are ${fmtPct(negRate(split.own), 0)} negative`)
  parts.push(`${split.own ? 'rival' : 'flaired'} fans ${fmtPct(negRate(split.rivals), 0)}`)
  parts.push(`unflaired commenters ${fmtPct(negRate(split.unflaired), 0)}`)
  const first = `Of what r/NBA says about ${name}, ${parts.join(', ')}.`
  if (lists.eligible < 2) return `${first} Fewer than two fanbases have ${fmtInt(floor)} comments about him, so no fanbase stands out.`
  const top = lists.haters[0]!
  const kind = lists.defenders[0]!
  return `${first} Among the ${fmtInt(lists.eligible)} fanbases with at least ${fmtInt(floor)} comments, ${possessive(top.team)} are hardest on him at ${fmtPct(negRate(top), 0)} negative and ${possessive(kind.team)} kindest at ${fmtPct(posRate(kind), 0)} positive.`
}
