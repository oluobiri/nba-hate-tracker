import { describe, expect, it } from 'vitest'

import { assertManifest, assertParquetSchema, assertRecaps, assertTables } from './assert'
import { SCHEMA_VERSION, TABLE_NAMES } from './contract'
import type { Manifest, RecapEntry, Tables } from './types.gen'

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
    posts: [{ post_id: 't3_x', title: 'Game Thread', created_utc: 1, score: 1, num_comments: 1, link_flair_text: null, post_type: 'game_thread', source: null, game_id: 'g1', is_primary: true }],
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
      accuracy: { labeled: false, drawn: null, scored: null, rejected: null, seed: null, drawn_at: null, rubric: null, groups: null, sentiment_agreement: null, sentiment_margin: null, target_agreement: null, target_margin: null, joint_agreement: null, joint_margin: null, by_class: null, class_mix: null, context_share: null, unsure_share: null, reject_share: null },
      floors: { fanbase_min_n: 1, week_min_n: 1, belt_min_n: 1, game_min_n: 1, race_entry_min_n: 1 },
      recaps: {
        room_bucket_seconds: 120,
        room_bodies_per_bucket: 2,
        anchor_window_seconds: 480,
        anchor_min_reactions: 3,
        anchor_vocabulary: {},
        reaction_lag: {
          candidates: 0,
          anchors: 0,
          games: 0,
          median_offset_seconds: null,
          p25_offset_seconds: null,
          p75_offset_seconds: null,
        },
      },
      metrics: {},
    },
    calendar: {},
    corpus: { raw_comments: 10, population_submitted: 5, classified: 5, usable: 5, attributed: 4 },
    populations: { live_thread: 'the live threads' },
    tables: registry,
    recaps: {},
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

// One curated recap of g1 for A Player: four periods summing to 8 of 10 live comments.
const recap = (extra: Partial<RecapEntry> = {}): RecapEntry => ({
  file: 'recaps/g1-a-player.json',
  rows: 50,
  game_id: 'g1',
  attributed_player: 'A Player',
  player_id: 1,
  slug: 'a-player',
  live_n: 10,
  room_n: 40,
  by_period: { '1': { neg: 1, pos: 1, neu: 0 }, '2': { neg: 2, pos: 0, neu: 0 }, '3': { neg: 1, pos: 0, neu: 1 }, '4': { neg: 2, pos: 0, neu: 0 } },
  swing: 0.5,
  minutes_diff: 0,
  population: 'live_thread',
  ...extra,
})

describe('assertRecaps', () => {
  const check = (key: string, entry: RecapEntry) => {
    const t = fixture()
    const m = manifestFor(t)
    m.recaps = { [key]: entry }
    return () => assertRecaps(m, t)
  }

  it('passes a consistent registry, and an empty one', () => {
    expect(check('g1-a-player', recap())).not.toThrow()
    const t = fixture()
    expect(() => assertRecaps(manifestFor(t), t)).not.toThrow()
  })

  it('refuses a key or file that does not spell game_id-slug', () => {
    expect(check('g1-b-player', recap())).toThrow('manifest.recaps.g1-b-player: key does not match g1-a-player')
    expect(check('g1-a-player', recap({ file: 'recaps/other.json' }))).toThrow('registers file recaps/other.json, expected recaps/g1-a-player.json')
  })

  it('refuses an entry whose game or player is not in the dimensions, or whom he did not dress for', () => {
    expect(check('g2-a-player', recap({ game_id: 'g2', file: 'recaps/g2-a-player.json' }))).toThrow('game_id g2 has no match in games.game_id')
    expect(check('g1-c-player', recap({ attributed_player: 'C Player', slug: 'c-player', file: 'recaps/g1-c-player.json' }))).toThrow('C Player has no match in players.attributed_player')
    expect(check('g1-a-player', recap({ player_id: 9 }))).toThrow('player_id 9 and slug a-player do not match players (1, a-player)')
    expect(check('g1-b-player', recap({ attributed_player: 'B Player', player_id: 2, slug: 'b-player', file: 'recaps/g1-b-player.json' }))).toThrow('B Player has no player_games row for g1')
  })

  it('refuses periods that are not 1..n with n ≥ 4, or a count that is not a non-negative integer', () => {
    const { '4': _four, ...three } = recap().by_period
    expect(check('g1-a-player', recap({ by_period: three }))).toThrow('by_period keys [1, 2, 3] are not 1..n with n ≥ 4')
    expect(check('g1-a-player', recap({ by_period: { ...recap().by_period, '6': { neg: 0, pos: 0, neu: 0 } } }))).toThrow('are not 1..n')
    expect(check('g1-a-player', recap({ by_period: { ...recap().by_period, '2': { neg: -1, pos: 0, neu: 0 } } }))).toThrow('by_period.2 has a count that is not a non-negative integer')
  })

  it('refuses counts that exceed the live thread, or a live thread that exceeds the room', () => {
    expect(check('g1-a-player', recap({ live_n: 7 }))).toThrow('by_period sums to 8, more than live_n 7')
    expect(check('g1-a-player', recap({ room_n: 9 }))).toThrow('live_n 10 exceeds room_n 9')
  })

  it('refuses a population the manifest does not define', () => {
    expect(check('g1-a-player', recap({ population: 'in_thread' }))).toThrow('population in_thread is not defined in manifest.populations')
  })
})
