// The Games section: the games a player dressed for, each with the room's
// verdict against his own season baseline. player_games is the spine (a
// game he did not dress for is not his game); game_sentiment joins on it
// and ships counts only, so the verdict is computed here, never shipped.
import type { GameSentimentRow, GamesRow, PlayerGamesRow } from '../data/types.gen'
import { fmtInt, fmtPct } from './format'
import { countsOf, gameScore, negRate, sumCounts } from './metrics'
import type { Counts } from './types'
import { weekOf } from './weeks'

export interface GameLine {
  gameId: string
  /** "YYYY-MM-DD". */
  date: string
  opponent: string
  opponentAbbr: string
  /** null on a neutral site: nobody hosted. */
  home: boolean | null
  win: boolean
  /** His team's score first: "112–98". */
  score: string
  seasonType: string
  minutes: number
  pts: number
  reb: number
  ast: number
  plusMinus: number
  gameScore: number
  /** "24 pts · 7 reb · 9 ast", or "DNP" when he dressed and did not play. */
  line: string
  dnp: boolean
  /** The room's counts about him in this game's threads; null when nobody mentioned him. */
  counts: Counts | null
  /** At or above the game floor: the room talked about him. */
  talked: boolean
  /** This game's negative share minus his season baseline; null unless talked. */
  delta: number | null
}

/** His dressed games in date order, joined to the room's counts and judged against `baseline`. */
export function buildGameLog(
  lines: readonly PlayerGamesRow[],
  sentiment: readonly GameSentimentRow[],
  games: ReadonlyMap<string, GamesRow>,
  abbr: ReadonlyMap<string, string>,
  baseline: Counts,
  floor: number,
): GameLine[] {
  const room = new Map(sentiment.map((r) => [r.game_id, countsOf(r)]))
  const base = negRate(baseline)
  return lines
    .flatMap((l) => {
      const g = games.get(l.game_id)
      if (!g) return []
      const ownIsHome = g.home_team === l.roster_team
      const ours = ownIsHome ? g.home_score : g.away_score
      const theirs = ownIsHome ? g.away_score : g.home_score
      const counts = room.get(l.game_id) ?? null
      const talked = counts !== null && counts.total >= floor
      const dnp = l.minutes === 0
      return [
        {
          gameId: l.game_id,
          date: g.game_date,
          opponent: l.opponent,
          opponentAbbr: abbr.get(l.opponent) ?? l.opponent,
          home: l.is_home,
          win: l.wl === 'W',
          score: `${ours}–${theirs}`,
          seasonType: g.season_type,
          minutes: l.minutes,
          pts: l.pts,
          reb: l.reb,
          ast: l.ast,
          plusMinus: l.plus_minus,
          gameScore: dnp ? 0 : gameScore(l),
          line: dnp ? 'DNP' : `${l.pts} pts · ${l.reb} reb · ${l.ast} ast`,
          dnp,
          counts,
          talked,
          delta: talked ? negRate(counts) - base : null,
        },
      ]
    })
    .toSorted((a, b) => a.date.localeCompare(b.date) || a.gameId.localeCompare(b.gameId))
}

/** Games he played (not DNP) that the room talked about. */
const graded = (log: readonly GameLine[]): GameLine[] => log.filter((g) => g.talked && !g.dnp)

/** The room in his wins vs his losses, from summed counts; a side is null under the floor. */
export function winLossSplit(log: readonly GameLine[], floor: number): { wins: Counts | null; losses: Counts | null } {
  const side = (win: boolean) => {
    const c = sumCounts(graded(log).filter((g) => g.win === win).map((g) => g.counts!))
    return c.total >= floor ? c : null
  }
  return { wins: side(true), losses: side(false) }
}

export interface ScatterPoint {
  gameId: string
  x: number
  y: number
  win: boolean
  label: string
}

/** Game Score against the negative share, one point per graded game. */
export function scatterPoints(log: readonly GameLine[]): ScatterPoint[] {
  return graded(log).map((g) => ({
    gameId: g.gameId,
    x: g.gameScore,
    y: negRate(g.counts!),
    win: g.win,
    label: `${g.win ? 'W' : 'L'} ${g.home === false ? '@' : 'vs'} ${g.opponentAbbr} ${g.score}: Game Score ${g.gameScore.toFixed(1)}, ${fmtPct(negRate(g.counts!), 0)} negative`,
  }))
}

// Correlation bands for the scatter's lead sentence: a page choice.
const STRONG = 0.3
const WEAK = 0.1

/** The plain-words lead over the scatter, by the sign and size of r. */
export function scatterLead(name: string, n: number, r: number | null): string {
  if (r === null) return `Too few games to say whether the room grades ${name}'s box score.`
  const over = `across ${fmtInt(n)} games the room talked about`
  if (r <= -STRONG) return `Bad nights get punished: ${over}, the negative share falls as ${name}'s Game Score rises.`
  if (r <= -WEAK) return `Bad nights get punished, mildly: ${over}, the negative share drifts down as ${name}'s Game Score rises.`
  if (r < WEAK) return `The room barely grades the box score: ${over}, ${name}'s Game Score and the negative share move independently.`
  if (r < STRONG) return `Good nights get punished, mildly: ${over}, the negative share drifts up as ${name}'s Game Score rises.`
  return `Good nights get punished: ${over}, the negative share rises with ${name}'s Game Score.`
}

/** For a player with no box line all season. */
export function neverDressedSentence(name: string, threadCount: number, floor: number): string {
  const threads = threadCount === 1 ? 'game thread' : 'game threads'
  return `${name} never dressed this season; the room still talked about him in ${fmtInt(threadCount)} ${threads} with at least ${fmtInt(floor)} comments each.`
}

/** How many of a player's game-thread rows reach the floor, dressed or not. */
export function talkedThreads(sentiment: readonly GameSentimentRow[], floor: number): number {
  return sentiment.filter((r) => r.comment_count >= floor).length
}

/** One sentence for the section: how many games the room graded and the win/loss split against his baseline. */
export function gamesSummary(name: string, log: readonly GameLine[], baseline: Counts, floor: number): string {
  const talked = log.filter((g) => g.talked).length
  const first = `The room talked about ${name} in ${fmtInt(talked)} of his ${fmtInt(log.length)} games, at least ${fmtInt(floor)} comments each.`
  const { wins, losses } = winLossSplit(log, floor)
  if (!wins || !losses) return `${first} Too few graded games on one side to split wins from losses.`
  const w = negRate(wins)
  const l = negRate(losses)
  const verb = l > w ? 'harsher' : l < w ? 'kinder' : 'no different'
  return `${first} It was ${verb} after losses: ${fmtPct(l, 0)} negative in losses against ${fmtPct(w, 0)} in wins, on a season baseline of ${fmtPct(negRate(baseline), 0)}.`
}

/** The log bucketed by spine week, for the timeline's week tooltips. */
export function weekGames(log: readonly GameLine[], spine: readonly string[]): GameLine[][] {
  const index = new Map(spine.map((w, i) => [w, i]))
  const out: GameLine[][] = spine.map(() => [])
  for (const g of log) {
    const i = index.get(weekOf(g.date))
    if (i !== undefined) out[i]!.push(g)
  }
  return out
}
