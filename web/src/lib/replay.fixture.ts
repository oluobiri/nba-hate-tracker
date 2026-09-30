// Row builders for the clock and replay tests: one recap frame row each,
// every column defaulted, overrides on top. Test-only; nothing ships it.
import type { RecapCommentsRow, RecapPeriodsRow, RecapPlaysRow } from '../data/types.gen'

const secs = (n: number): number => (n <= 4 ? n * 720 : 2880 + (n - 4) * 300)

export const period = (n: number, startWall: number, endWall: number): RecapPeriodsRow => ({
  period: n,
  start_seconds: secs(n - 1),
  end_seconds: secs(n),
  start_wall: startWall,
  end_wall: endWall,
  start_action_number: 0,
  end_action_number: 0,
})

export const play = (o: Partial<RecapPlaysRow> = {}): RecapPlaysRow => ({
  action_number: 0,
  paired_action_number: null,
  period: 1,
  clock: 'PT12M00.00S',
  game_seconds: 0,
  wall_clock: 0,
  kind: 'shot',
  action_type: '',
  sub_type: '',
  description: '',
  team_tricode: null,
  person_id: 0,
  player_name_i: null,
  is_focus: false,
  made: null,
  shot_value: 0,
  x_legacy: null,
  y_legacy: null,
  shot_distance: null,
  score_home: 0,
  score_away: 0,
  pts: null,
  reb: null,
  ast: null,
  blk: null,
  stl: null,
  tov: null,
  pf: null,
  ...o,
})

export const comment = (o: Partial<RecapCommentsRow> = {}): RecapCommentsRow => ({
  comment_id: 'c',
  post_id: 't3_x',
  created_utc: 0,
  game_seconds: 0,
  phase: 'live',
  sentiment: 'neg',
  score: 1,
  fan_team: null,
  player_id: null,
  is_focus: true,
  body: 'b',
  ...o,
})

/** Tip at 1000. Four periods of 1,000 wall seconds; breaks of 200, 1,000 and 200. */
export const REGULATION: RecapPeriodsRow[] = [period(1, 1000, 2000), period(2, 2200, 3200), period(3, 4200, 5200), period(4, 5400, 6400)]
export const OVERTIME: RecapPeriodsRow[] = [...REGULATION, period(5, 6600, 6900), period(6, 7000, 7300)]
