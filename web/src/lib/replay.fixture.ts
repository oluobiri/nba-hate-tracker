// Row builders for the clock and replay tests: one recap frame row each,
// every column defaulted, overrides on top. Test-only; nothing ships it.
import type { RecapCommentsRow, RecapPeriodsRow, RecapPlaysRow, RecapStintsRow } from '../data/types.gen'

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
  action_type: '2pt',
  sub_type: '',
  description: '',
  team_tricode: null,
  person_id: 0,
  player_name_i: null,
  assist_person_id: null,
  is_focus: false,
  made: null,
  shot_value: 0,
  x: null,
  y: null,
  shot_distance: null,
  score_home: 0,
  score_away: 0,
  ...o,
})

export const stint = (o: Partial<RecapStintsRow> = {}): RecapStintsRow => ({
  person_id: 1,
  team_tricode: 'AAA',
  period: 1,
  start_seconds: 0,
  end_seconds: 720,
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

/** The feed's clock string for a game second inside its period. */
export const clockOf = (p: RecapPeriodsRow, g: number): string => {
  const left = p.end_seconds - g
  return `PT${String(Math.floor(left / 60)).padStart(2, '0')}M${String(left % 60).padStart(2, '0')}.00S`
}

/**
 * A two-period game with the tip at wall 1000. Period 1: a shot at 10 s, a timeout at
 * 20 s that holds the clock for 60 wall seconds, a free throw, then 700 game seconds in
 * 720 wall seconds to the buzzer. A 200 s halftime. Period 2: a missed three, the
 * buzzer after a 60 s stoppage.
 */
export function smallGame(): { periods: RecapPeriodsRow[]; plays: RecapPlaysRow[] } {
  const p1 = period(1, 1000, 1800)
  const p2 = period(2, 2000, 2800)
  const periods = [p1, p2]
  const row = (p: RecapPeriodsRow, g: number, wall: number, o: Partial<RecapPlaysRow>): RecapPlaysRow =>
    play({ period: p.period, game_seconds: g, clock: clockOf(p, g), wall_clock: wall, ...o })
  const plays: RecapPlaysRow[] = [
    row(p1, 0, 1000, { action_number: 2, kind: 'period_start', action_type: 'period', sub_type: 'start', description: 'Period Start' }),
    row(p1, 10, 1010, { action_number: 4, kind: 'shot', action_type: '2pt', made: true, shot_value: 2, score_home: 2, person_id: 1, team_tricode: 'AAA', x: 90, y: 50 }),
    row(p1, 20, 1020, { action_number: 6, kind: 'timeout', action_type: 'timeout', sub_type: 'full', description: 'AAA Timeout', team_tricode: 'AAA', score_home: 2 }),
    row(p1, 20, 1080, { action_number: 8, kind: 'free_throw', action_type: 'freethrow', made: true, shot_value: 1, score_home: 2, score_away: 1, person_id: 2, team_tricode: 'BBB' }),
    row(p1, 720, 1800, { action_number: 10, kind: 'period_end', action_type: 'period', sub_type: 'end', description: 'Period End', score_home: 2, score_away: 1 }),
    row(p2, 720, 2000, { action_number: 12, kind: 'period_start', action_type: 'period', sub_type: 'start', description: 'Period Start', score_home: 2, score_away: 1 }),
    row(p2, 1000, 2300, { action_number: 14, kind: 'shot', action_type: '3pt', made: false, shot_value: 3, score_home: 2, score_away: 1, person_id: 2, team_tricode: 'BBB', x: 10, y: 40 }),
    row(p2, 1440, 2800, { action_number: 16, kind: 'period_end', action_type: 'period', sub_type: 'end', description: 'Period End', score_home: 2, score_away: 1 }),
  ]
  return { periods, plays }
}
