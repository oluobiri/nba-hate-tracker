// A player without a roster team: his curated status where "Free agent"
// would print, and the sentence of what happened. The copy and the players
// table must agree, both ways, or the build fails naming the player.
import type { PlayersRow } from '../data/types.gen'
import { PLAYER_STATUS, type PlayerStatusCopy } from './player-status-copy'

export type StatusIdentity = Pick<PlayersRow, 'attributed_player' | 'slug' | 'roster_team'>

/** His status without a roster team; null on a roster. Throws where the copy and the table disagree. */
export function playerStatus(player: StatusIdentity, copy: Readonly<Record<string, PlayerStatusCopy>> = PLAYER_STATUS): PlayerStatusCopy | null {
  const entry = copy[player.slug]
  if (player.roster_team) {
    if (entry) throw new Error(`player status: ${player.attributed_player} is listed as ${entry.status} but has a roster team (${player.roster_team})`)
    return null
  }
  if (!entry) throw new Error(`player status: ${player.attributed_player} has no roster team and no entry in player-status-copy`)
  return entry
}

/** Every player against the copy, once per build; a listed slug no player has fails it too. */
export function checkStatusCopy(players: readonly StatusIdentity[], copy: Readonly<Record<string, PlayerStatusCopy>> = PLAYER_STATUS): void {
  for (const p of players) playerStatus(p, copy)
  const slugs = new Set(players.map((p) => p.slug))
  for (const slug of Object.keys(copy)) if (!slugs.has(slug)) throw new Error(`player status: ${slug} is listed but no player has that slug`)
}

/** Under the name on a row: the roster abbreviation, or his status. */
export function teamLine(player: StatusIdentity, abbrOf: ReadonlyMap<string, string>, copy: Readonly<Record<string, PlayerStatusCopy>> = PLAYER_STATUS): string {
  return player.roster_team ? (abbrOf.get(player.roster_team) ?? player.roster_team) : playerStatus(player, copy)!.status
}

/** The Games lede: what happened to him closes the summary, or stands alone when he never dressed. */
export function gamesLede(summary: string | null, status: PlayerStatusCopy | null, neverDressed: () => string): string {
  if (summary === null) return status ? status.text : neverDressed()
  return status ? `${summary} ${status.text}` : summary
}
