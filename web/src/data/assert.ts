// Contract assertions over the loaded season. Each failure names the
// table (and column, row or key) so a bad drop fails the build with a
// pointer, not a stack trace. Returns the warnings that are known gaps
// rather than failures.
import { type ColumnSpec, ContractError, SCHEMA_VERSION, TABLE_NAMES } from './contract'
import { parquetDtype, type SchemaElement, topLevelColumns } from './rows'
import type { Manifest, Tables } from './types.gen'

// Rates are rounded to 4 dp upstream: a half-unit tie is legitimate, so
// allow it plus float noise.
const RATE_TOLERANCE = 5e-5 + 1e-9

export function assertManifest(manifest: Manifest, season: string): void {
  if (manifest.schema_version !== SCHEMA_VERSION)
    throw new ContractError(`manifest: schema_version ${manifest.schema_version}, contract is ${SCHEMA_VERSION}`)
  if (manifest.season !== season) throw new ContractError(`manifest: season ${manifest.season}, expected ${season}`)
  const registry = Object.keys(manifest.tables).toSorted()
  const expected = [...TABLE_NAMES].toSorted()
  if (registry.join(',') !== expected.join(','))
    throw new ContractError(`manifest: table registry [${registry.join(', ')}] differs from the contract [${expected.join(', ')}]`)
}

export function assertParquetSchema(table: string, schema: readonly SchemaElement[], columns: readonly ColumnSpec[]): void {
  const actual = topLevelColumns(schema).map(({ el, leaf }) => ({ name: el.name, dtype: parquetDtype(el, leaf) }))
  if (actual.length !== columns.length)
    throw new ContractError(`${table}: ${actual.length} columns in the file, contract has ${columns.length}`)
  columns.forEach((col, i) => {
    const got = actual[i] as { name: string; dtype: string | null }
    if (got.name !== col.name) throw new ContractError(`${table}: column ${i} is ${got.name}, contract has ${col.name}`)
    if (got.dtype !== col.dtype) throw new ContractError(`${table}.${col.name}: file dtype ${got.dtype ?? 'unknown'}, contract has ${col.dtype}`)
  })
}

interface RateRow {
  neg_count: number
  neu_count: number
  pos_count: number
  comment_count: number
  neg_rate: number
  pos_rate: number
  net_sentiment: number
  polarization: number
}

function assertRates<T extends RateRow>(table: string, rows: readonly T[], key: (r: T) => string): void {
  rows.forEach((r, i) => {
    const total = r.comment_count
    if (r.neg_count + r.neu_count + r.pos_count !== total)
      throw new ContractError(`${table}: counts do not sum to comment_count at row ${i} (${key(r)})`)
    const expect = (name: keyof RateRow, value: number) => {
      if (Math.abs(r[name] - value) > RATE_TOLERANCE)
        throw new ContractError(`${table}.${name}: ${r[name]} at row ${i} (${key(r)}), counts give ${value.toFixed(4)}`)
    }
    if (total === 0) return
    expect('neg_rate', r.neg_count / total)
    expect('pos_rate', r.pos_count / total)
    expect('net_sentiment', (r.pos_count - r.neg_count) / total)
    expect('polarization', (r.pos_count + r.neg_count) / total)
  })
}

function assertUnique<T>(table: string, column: string, rows: readonly T[], pick: (r: T) => unknown): void {
  const seen = new Set<unknown>()
  for (const r of rows) {
    const v = pick(r)
    if (seen.has(v)) throw new ContractError(`${table}.${column}: duplicate ${JSON.stringify(v)}`)
    seen.add(v)
  }
}

function assertForeignKeys<T>(
  table: string,
  column: string,
  rows: readonly T[],
  pick: (r: T) => string | number | null,
  target: string,
  keys: ReadonlySet<string | number>,
): void {
  rows.forEach((r, i) => {
    const v = pick(r)
    if (v !== null && !keys.has(v))
      throw new ContractError(`${table}.${column}: ${JSON.stringify(v)} at row ${i} has no match in ${target}`)
  })
}

export function assertTables(tables: Tables, manifest: Manifest): string[] {
  const warnings: string[] = []

  for (const name of TABLE_NAMES) {
    const rows = tables[name]
    const expected = manifest.tables[name]?.rows
    if (rows.length !== expected) throw new ContractError(`${name}: ${rows.length} rows, manifest registers ${expected}`)
  }

  const players = new Set(tables.players.map((p) => p.attributed_player))
  const playerIds = new Set(tables.players.map((p) => p.player_id))
  const teams = new Set(tables.teams.map((t) => t.team))
  const games = new Set(tables.games.map((g) => g.game_id))
  const posts = new Set(tables.posts.map((p) => p.post_id))

  assertUnique('players', 'attributed_player', tables.players, (p) => p.attributed_player)
  assertUnique('players', 'player_id', tables.players, (p) => p.player_id)
  assertUnique('players', 'slug', tables.players, (p) => p.slug)
  assertUnique('teams', 'team', tables.teams, (t) => t.team)
  assertUnique('teams', 'abbreviation', tables.teams, (t) => t.abbreviation)
  assertUnique('games', 'game_id', tables.games, (g) => g.game_id)
  assertUnique('posts', 'post_id', tables.posts, (p) => p.post_id)

  assertRates('player_overall', tables.player_overall, (r) => r.attributed_player)
  assertRates('player_temporal', tables.player_temporal, (r) => `${r.attributed_player} ${r.week}`)
  assertRates('player_fan_team', tables.player_fan_team, (r) => `${r.attributed_player} × ${r.fan_team}`)
  assertRates('fan_team_overall', tables.fan_team_overall, (r) => r.fan_team)
  assertRates('game_sentiment', tables.game_sentiment, (r) => `${r.attributed_player} ${r.game_id}`)

  // Weekly rows are keyed to a Monday at 00:00, and sum back to the season row.
  const weekly = new Map<string, { neg: number; neu: number; pos: number; total: number }>()
  tables.player_temporal.forEach((r, i) => {
    const d = new Date(`${r.week}Z`)
    if (Number.isNaN(d.getTime()) || d.getUTCDay() !== 1 || !r.week.endsWith('T00:00:00'))
      throw new ContractError(`player_temporal.week: ${r.week} at row ${i} is not a Monday at 00:00`)
    const w = weekly.get(r.attributed_player) ?? { neg: 0, neu: 0, pos: 0, total: 0 }
    w.neg += r.neg_count
    w.neu += r.neu_count
    w.pos += r.pos_count
    w.total += r.comment_count
    weekly.set(r.attributed_player, w)
  })
  for (const o of tables.player_overall) {
    const w = weekly.get(o.attributed_player)
    if (!w || w.neg !== o.neg_count || w.neu !== o.neu_count || w.pos !== o.pos_count || w.total !== o.comment_count)
      throw new ContractError(`player_temporal: weekly counts for ${o.attributed_player} do not sum to player_overall`)
  }

  // Every FK resolves to its dimension's canonical key.
  for (const name of ['player_overall', 'player_temporal', 'player_fan_team', 'game_sentiment', 'player_games', 'comment_samples'] as const) {
    const rows: readonly { attributed_player: string; player_id: number }[] = tables[name]
    assertForeignKeys(name, 'attributed_player', rows, (r) => r.attributed_player, 'players.attributed_player', players)
    assertForeignKeys(name, 'player_id', rows, (r) => r.player_id, 'players.player_id', playerIds)
  }
  assertForeignKeys('players', 'roster_team', tables.players, (p) => p.roster_team, 'teams.team', teams)
  assertForeignKeys('player_fan_team', 'fan_team', tables.player_fan_team, (r) => r.fan_team, 'teams.team', teams)
  assertForeignKeys('fan_team_overall', 'fan_team', tables.fan_team_overall, (r) => r.fan_team, 'teams.team', teams)
  assertForeignKeys('comment_samples', 'fan_team', tables.comment_samples, (r) => r.fan_team, 'teams.team', teams)
  assertForeignKeys('games', 'home_team', tables.games, (g) => g.home_team, 'teams.team', teams)
  assertForeignKeys('games', 'away_team', tables.games, (g) => g.away_team, 'teams.team', teams)
  assertForeignKeys('games', 'winner', tables.games, (g) => g.winner, 'teams.team', teams)
  assertForeignKeys('player_games', 'roster_team', tables.player_games, (r) => r.roster_team, 'teams.team', teams)
  assertForeignKeys('player_games', 'opponent', tables.player_games, (r) => r.opponent, 'teams.team', teams)
  assertForeignKeys('player_games', 'game_id', tables.player_games, (r) => r.game_id, 'games.game_id', games)
  assertForeignKeys('game_sentiment', 'game_id', tables.game_sentiment, (r) => r.game_id, 'games.game_id', games)
  assertForeignKeys('posts', 'game_id', tables.posts, (p) => p.game_id, 'games.game_id', games)

  // Known gap: a receipt's post can be missing from the bridge (absent from
  // the raw posts download). The card renders without its title.
  const orphaned = tables.comment_samples.filter((r) => !posts.has(r.link_id)).length
  if (orphaned) warnings.push(`comment_samples: ${orphaned} receipt(s) point at a post absent from posts`)

  return warnings
}
