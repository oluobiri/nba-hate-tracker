import { describe, expect, it } from 'vitest'

import { assertManifest, assertParquetSchema, assertTables } from './assert'
import { SCHEMA_VERSION, TABLE_NAMES } from './contract'
import type { Manifest, Tables } from './types.gen'

const counts = (neg: number, neu: number, pos: number) => {
  const total = neg + neu + pos
  return {
    neg_count: neg,
    neu_count: neu,
    pos_count: pos,
    comment_count: total,
    neg_rate: total ? +(neg / total).toFixed(4) : 0,
    pos_rate: total ? +(pos / total).toFixed(4) : 0,
    net_sentiment: total ? +((pos - neg) / total).toFixed(4) : 0,
    polarization: total ? +((pos + neg) / total).toFixed(4) : 0,
  }
}

function fixture(): Tables {
  const tables: Tables = {
    players: [
      { attributed_player: 'A Player', slug: 'a-player', roster_team: 'Team One', conference: 'West', player_id: 1, headshot_url: '', position: 'G', birth_date: null, experience: null, school: null, jersey_number: null, height: null, weight: null },
      { attributed_player: 'B Player', slug: 'b-player', roster_team: null, conference: null, player_id: 2, headshot_url: '', position: null, birth_date: null, experience: null, school: null, jersey_number: null, height: null, weight: null },
    ],
    teams: [
      { team: 'Team One', abbreviation: 'ONE', conference: 'West', team_id: 10, logo_url: '' },
      { team: 'Team Two', abbreviation: 'TWO', conference: 'East', team_id: 20, logo_url: '' },
    ],
    games: [
      { game_id: 'g1', game_date: '2025-10-21', season_type: 'regular_season', nba_cup_final: false, neutral_site: false, home_team: 'Team One', away_team: 'Team Two', home_score: 100, away_score: 90, winner: 'Team One', playoff_round: null, playoff_series: null, playoff_game: null },
    ],
    player_overall: [
      { attributed_player: 'A Player', player_id: 1, ...counts(6, 3, 1) },
      { attributed_player: 'B Player', player_id: 2, ...counts(1, 1, 2) },
    ],
    player_temporal: [
      { attributed_player: 'A Player', player_id: 1, week: '2025-10-20T00:00:00', ...counts(4, 2, 0) },
      { attributed_player: 'A Player', player_id: 1, week: '2025-10-27T00:00:00', ...counts(2, 1, 1) },
      { attributed_player: 'B Player', player_id: 2, week: '2025-10-20T00:00:00', ...counts(1, 1, 2) },
    ],
    player_fan_team: [{ attributed_player: 'A Player', player_id: 1, fan_team: 'Team Two', ...counts(3, 0, 0) }],
    fan_team_overall: [{ fan_team: 'Team Two', ...counts(3, 0, 0), abbreviation: 'TWO', conference: 'East', logo_url: '' }],
    game_sentiment: [{ attributed_player: 'A Player', player_id: 1, game_id: 'g1', ...counts(2, 0, 0), thread_comment_count: 5 }],
    player_games: [{ game_id: 'g1', attributed_player: 'A Player', player_id: 1, roster_team: 'Team One', opponent: 'Team Two', is_home: true, wl: 'W', minutes: 30, fgm: 1, fga: 2, fg3m: 0, fg3a: 0, ftm: 0, fta: 0, oreb: 0, dreb: 0, reb: 0, ast: 0, stl: 0, blk: 0, tov: 0, pf: 0, pts: 2, plus_minus: 1 }],
    posts: [{ post_id: 't3_x', title: 'Game Thread', created_utc: 1, score: 1, num_comments: 1, link_flair_text: null, post_type: 'game_thread', game_id: 'g1', is_primary: true }],
    comment_samples: [{ attributed_player: 'A Player', player_id: 1, sentiment: 'neg', rank: 1, comment_id: 'c1', link_id: 't3_x', body: 'nope', score: 3, created_utc: 1, fan_team: null }],
    corpus_daily: [{ day: '2025-10-21', raw_comments: 10, population_submitted: 5, usable: 5, attributed: 4 }],
  }
  return tables
}

function manifestFor(tables: Tables): Manifest {
  const registry = Object.fromEntries(
    TABLE_NAMES.map((name) => [name, { file: `${name}.parquet`, rows: tables[name].length, population: null }]),
  )
  return {
    schema_version: SCHEMA_VERSION,
    season: '2025-26',
    generated_at: 'now',
    config_versions: {},
    classifiers: {},
    snapshots: {},
    rules: {
      qualified_threshold: 5,
      samples: { top_n: 1, min_confidence: 0.9, max_body_chars: 500, requires_target: false, pool_k: 1, admission: 'verified' },
      receipts: { verified: true, coverage: null, precision: null, attribution_toward_share: null },
      floors: { fanbase_min_n: 1, week_min_n: 1, belt_min_n: 1, game_min_n: 1 },
      metrics: {},
    },
    calendar: {},
    corpus: { raw_comments: 10, population_submitted: 5, classified: 5, usable: 5, attributed: 4 },
    populations: {},
    tables: registry,
  }
}

describe('assertManifest', () => {
  it('accepts a matching manifest and refuses the wrong version, season or registry', () => {
    const m = manifestFor(fixture())
    expect(() => assertManifest(m, '2025-26')).not.toThrow()
    expect(() => assertManifest({ ...m, schema_version: 4 }, '2025-26')).toThrow('manifest: schema_version 4')
    expect(() => assertManifest(m, '2024-25')).toThrow('manifest: season 2025-26, expected 2024-25')
    const { players: _dropped, ...rest } = m.tables
    expect(() => assertManifest({ ...m, tables: rest }, '2025-26')).toThrow('table registry')
  })
})

describe('assertParquetSchema', () => {
  const columns = [
    { name: 'id', dtype: 'int64', nullable: false },
    { name: 'day', dtype: 'date', nullable: false },
  ]
  const schema = [
    { name: 'root', num_children: 2 },
    { name: 'id', type: 'INT64' },
    { name: 'day', type: 'INT32', logical_type: { type: 'DATE' } },
  ]

  it('accepts a file whose columns match in order and dtype', () => {
    expect(() => assertParquetSchema('t', schema, columns)).not.toThrow()
  })

  it('names the mismatch', () => {
    expect(() => assertParquetSchema('t', schema.slice(0, 2), columns)).toThrow('t: 1 columns in the file, contract has 2')
    expect(() => assertParquetSchema('t', [schema[0]!, schema[2]!, schema[1]!], columns)).toThrow('t: column 0 is day')
    expect(() => assertParquetSchema('t', [schema[0]!, { name: 'id', type: 'DOUBLE' }, schema[2]!], columns)).toThrow('t.id: file dtype float64, contract has int64')
  })
})

describe('assertTables', () => {
  it('passes a consistent season and reports no warnings', () => {
    const t = fixture()
    expect(assertTables(t, manifestFor(t))).toEqual([])
  })

  it('refuses a row count that differs from the registry', () => {
    const t = fixture()
    const m = manifestFor(t)
    m.tables.teams!.rows = 3
    expect(() => assertTables(t, m)).toThrow('teams: 2 rows, manifest registers 3')
  })

  it('refuses a rate that disagrees with its counts', () => {
    const t = fixture()
    t.player_overall[0]!.neg_rate = 0.3
    expect(() => assertTables(t, manifestFor(t))).toThrow('player_overall.neg_rate: 0.3 at row 0 (A Player), counts give 0.6000')
  })

  it('refuses counts that do not sum to comment_count', () => {
    const t = fixture()
    t.fan_team_overall[0]!.neu_count = 9
    expect(() => assertTables(t, manifestFor(t))).toThrow('fan_team_overall: counts do not sum')
  })

  it('refuses a week that is not a Monday at midnight', () => {
    const t = fixture()
    t.player_temporal[0]!.week = '2025-10-21T00:00:00'
    expect(() => assertTables(t, manifestFor(t))).toThrow('is not a Monday at 00:00')
  })

  it('refuses weekly counts that do not sum to the season row', () => {
    const t = fixture()
    t.player_temporal.splice(1, 1, { ...t.player_temporal[1]!, ...counts(1, 1, 1) })
    expect(() => assertTables(t, manifestFor(t))).toThrow('weekly counts for A Player do not sum')
  })

  it('refuses a duplicate slug', () => {
    const t = fixture()
    t.players[1]!.slug = 'a-player'
    expect(() => assertTables(t, manifestFor(t))).toThrow('players.slug: duplicate "a-player"')
  })

  it('refuses a foreign key with no match, naming the target', () => {
    const t = fixture()
    t.player_games[0]!.opponent = 'Team Nine'
    expect(() => assertTables(t, manifestFor(t))).toThrow('player_games.opponent: "Team Nine" at row 0 has no match in teams.team')
  })

  it('reports a receipt whose post is missing as a warning, not a failure', () => {
    const t = fixture()
    t.comment_samples[0]!.link_id = 't3_gone'
    expect(assertTables(t, manifestFor(t))).toEqual(['comment_samples: 1 receipt(s) point at a post absent from posts'])
  })
})
