// The Games section: the games a player dressed for, each with the room's
// verdict against his own season, in net. player_games is the spine (a
// game he did not dress for is not his game); game_sentiment joins on it
// and ships counts only, so the verdict is computed here, never shipped.
import type { GameSentimentRow, GamesRow, PlayerGamesRow } from '../data/types.gen'
import { fmtInt, fmtPct } from './format'
import { countsOf, gameScore, negRate, netSentiment, posRate, sumCounts } from './metrics'
import { fmtNet } from './net'
import type { Counts } from './types'
import { PHASE_LABELS, type Phase, weekLabel, weekOf } from './weeks'

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
  /** "R4 G5" in the playoffs, "Play-in", "Pre"; blank in the regular season. */
  phase: string
  minutes: number
  pts: number
  reb: number
  ast: number
  /** "9-18". */
  fg: string
  /** "2-6". */
  fg3: string
  tov: number
  plusMinus: number
  gameScore: number
  /** "24 pts · 7 reb · 9 ast", or "DNP" when he dressed and did not play. */
  line: string
  dnp: boolean
  /** The room's counts about him in this game's threads; null when nobody mentioned him. */
  counts: Counts | null
  /** At or above the game floor: the room talked about him. */
  talked: boolean
  /** The room's net on him in this game, positive minus negative; null unless talked. */
  net: number | null
  /** This game's net minus his season net; null unless talked. */
  delta: number | null
  /** Every comment Reddit counts in the game's threads; null unless both threads are bridged. */
  reddit: number | null
  /** The recap of this game with him as its focus, when one is curated. */
  recapHref: string | null
}

/** "SAS 111 @ OKC 103": away first, as a box score reads. */
export function scoreLine(game: GamesRow, abbr: ReadonlyMap<string, string>): string {
  const a = (t: string) => abbr.get(t) ?? t
  return `${a(game.away_team)} ${game.away_score} @ ${a(game.home_team)} ${game.home_score}`
}

const ROUNDS: Record<number, string> = { 1: 'First round', 2: 'Conf. semifinals', 4: 'NBA Finals' }
const PHASE_TAGS: Record<string, string> = { pre_season: 'Pre', play_in: 'Play-in', playoffs: 'PO' }

/** The table's phase tag: round and game in the playoffs, the phase otherwise, blank in the regular season. */
export function phaseTag(game: GamesRow): string {
  if (game.season_type === 'playoffs' && game.playoff_round !== null && game.playoff_game !== null) return `R${Math.trunc(game.playoff_round)} G${Math.trunc(game.playoff_game)}`
  return PHASE_TAGS[game.season_type] ?? ''
}

/** The round of a playoff game, the conference named at round 3; the season phase otherwise. */
export function roundLabel(game: GamesRow, conferenceOf: ReadonlyMap<string, string>): string {
  const round = game.playoff_round === null ? null : Math.trunc(game.playoff_round)
  if (game.season_type !== 'playoffs' || round === null) return PHASE_LABELS[game.season_type as Phase] ?? game.season_type
  if (round === 3) {
    const conference = conferenceOf.get(game.home_team) ?? conferenceOf.get(game.away_team)
    return conference ? `${conference} Finals` : 'Conference Finals'
  }
  return ROUNDS[round] ?? `Round ${round}`
}

export interface GameSide {
  abbr: string
  score: number
  won: boolean
}

export interface GameLineParts {
  round: string
  /** "Game 7"; null outside the playoffs. */
  game: string | null
  away: GameSide
  home: GameSide
  /** "May 30". */
  date: string
  /** "West Finals · Game 7 · SAS 111 @ OKC 103 · May 30". */
  text: string
}

/** One game as an eyebrow reads it, in parts so the winner can be set bold. */
export function gameLine(game: GamesRow, abbr: ReadonlyMap<string, string>, conferenceOf: ReadonlyMap<string, string>): GameLineParts {
  const a = (t: string) => abbr.get(t) ?? t
  const round = roundLabel(game, conferenceOf)
  const number = game.playoff_game === null ? null : `Game ${Math.trunc(game.playoff_game)}`
  const date = weekLabel(game.game_date)
  return {
    round,
    game: number,
    away: { abbr: a(game.away_team), score: game.away_score, won: game.winner === game.away_team },
    home: { abbr: a(game.home_team), score: game.home_score, won: game.winner === game.home_team },
    date,
    text: [round, number, scoreLine(game, abbr), date].filter(Boolean).join(' · '),
  }
}

/** His dressed games in date order, joined to the room's counts and judged in net against `baseline`. */
export function buildGameLog(
  lines: readonly PlayerGamesRow[],
  sentiment: readonly GameSentimentRow[],
  games: ReadonlyMap<string, GamesRow>,
  abbr: ReadonlyMap<string, string>,
  baseline: Counts,
  floor: number,
  recapHrefs: ReadonlyMap<string, string> = new Map(),
  reddit: ReadonlyMap<string, number> = new Map(),
): GameLine[] {
  const room = new Map(sentiment.map((r) => [r.game_id, countsOf(r)]))
  const base = netSentiment(baseline)
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
          phase: phaseTag(g),
          minutes: l.minutes,
          pts: l.pts,
          reb: l.reb,
          ast: l.ast,
          fg: `${l.fgm}-${l.fga}`,
          fg3: `${l.fg3m}-${l.fg3a}`,
          tov: l.tov,
          plusMinus: l.plus_minus,
          gameScore: dnp ? 0 : gameScore(l),
          line: dnp ? 'DNP' : `${l.pts} pts · ${l.reb} reb · ${l.ast} ast`,
          dnp,
          counts,
          talked,
          net: talked ? netSentiment(counts) : null,
          delta: talked ? netSentiment(counts) - base : null,
          reddit: reddit.get(l.game_id) ?? null,
          recapHref: recapHrefs.get(l.game_id) ?? null,
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

/** Game Score against the room's net, one point per graded game. */
export function scatterPoints(log: readonly GameLine[]): ScatterPoint[] {
  return graded(log).map((g) => ({
    gameId: g.gameId,
    x: g.gameScore,
    y: g.net!,
    win: g.win,
    label: `${g.win ? 'W' : 'L'} ${g.home === false ? '@' : 'vs'} ${g.opponentAbbr} ${g.score}: Game Score ${g.gameScore.toFixed(1)}, net ${fmtNet(g.net)} from ${fmtInt(g.counts!.total)} comments`,
  }))
}

// Correlation bands for the scatter's lead sentence: a page choice.
const STRONG = 0.3
const WEAK = 0.1

/** The plain-words lead over the scatter, by the sign and size of r between Game Score and net. */
export function scatterLead(name: string, n: number, r: number | null): string {
  if (r === null) return `Too few games to say whether the room grades ${name}'s box score.`
  const over = `across ${fmtInt(n)} games the room talked about`
  if (r >= STRONG) return `Bad nights get punished: ${over}, net sentiment rises with ${name}'s Game Score.`
  if (r >= WEAK) return `Bad nights get punished, mildly: ${over}, net sentiment drifts up as ${name}'s Game Score rises.`
  if (r > -WEAK) return `The room barely grades the box score: ${over}, ${name}'s Game Score and net sentiment move independently.`
  if (r > -STRONG) return `Good nights get punished, mildly: ${over}, net sentiment drifts down as ${name}'s Game Score rises.`
  return `Good nights get punished: ${over}, net sentiment falls as ${name}'s Game Score rises.`
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

/** "−32 in losses (44% negative, 12% positive)": net with both shares beside it, since net alone can hide a split room. */
const netSide = (c: Counts, label: string): string => `${fmtNet(netSentiment(c))} in ${label} (${fmtPct(negRate(c), 0)} negative, ${fmtPct(posRate(c), 0)} positive)`

/** One sentence for the section: how many games the room graded and the win/loss split in net against his season. */
export function gamesSummary(name: string, log: readonly GameLine[], baseline: Counts, floor: number): string {
  const talked = log.filter((g) => g.talked).length
  const first = `The room talked about ${name} in ${fmtInt(talked)} of his ${fmtInt(log.length)} games, at least ${fmtInt(floor)} comments each.`
  const { wins, losses } = winLossSplit(log, floor)
  if (!wins || !losses) return `${first} Too few graded games on one side to split wins from losses.`
  // Read by the printed points: a gap that rounds to nothing is no different.
  const w = Math.round(100 * netSentiment(wins))
  const l = Math.round(100 * netSentiment(losses))
  const verb = l < w ? 'harsher' : l > w ? 'warmer' : 'no different'
  return `${first} It was ${verb} after losses: net ${netSide(losses, 'losses')} against ${netSide(wins, 'wins')}, on a season net of ${fmtNet(netSentiment(baseline))}.`
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

export interface SeasonAverages {
  gp: number
  ppg: number
  rpg: number
  apg: number
}

/** Regular-season averages over the games he played (not DNP); null when he played none. */
export function seasonAverages(log: readonly GameLine[]): SeasonAverages | null {
  const played = log.filter((g) => g.seasonType === 'regular_season' && !g.dnp)
  if (played.length === 0) return null
  const mean = (pick: (g: GameLine) => number) => played.reduce((a, g) => a + pick(g), 0) / played.length
  return { gp: played.length, ppg: mean((g) => g.pts), rpg: mean((g) => g.reb), apg: mean((g) => g.ast) }
}
