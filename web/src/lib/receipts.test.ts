import { describe, expect, it } from 'vitest'

import type { GamesRow, PostsRow } from '../data/types.gen'
import { commentDate, receiptContext } from './receipts'

const post = (post_type: string, game_id: string | null, title = 'A title'): PostsRow => ({
  post_id: 't3_x',
  title,
  created_utc: 0,
  score: 1,
  num_comments: 1,
  link_flair_text: null,
  post_type,
  game_id,
  is_primary: true,
})
const game: GamesRow = {
  game_id: 'g',
  game_date: '2026-05-07',
  season_type: 'playoffs',
  nba_cup_final: false,
  neutral_site: false,
  home_team: 'Detroit Pistons',
  away_team: 'Cleveland Cavaliers',
  home_score: 107,
  away_score: 97,
  winner: 'Detroit Pistons',
  playoff_round: 2,
  playoff_series: 1,
  playoff_game: 2,
}
const ABBR = new Map([
  ['Detroit Pistons', 'DET'],
  ['Cleveland Cavaliers', 'CLE'],
])

describe('receiptContext', () => {
  it('reads a game thread as the game, away at home, with the playoff round and the day', () => {
    expect(receiptContext(post('post_game_thread', 'g'), game, ABBR)).toEqual({ label: 'Post-game thread', text: 'CLE 97 @ DET 107 · R2 G2 · May 7' })
    expect(receiptContext(post('game_thread', 'g'), { ...game, playoff_round: null, playoff_game: null }, ABBR)).toEqual({ label: 'Game thread', text: 'CLE 97 @ DET 107 · May 7' })
  })

  it('reads any other post as its title, and a game thread without its game likewise', () => {
    expect(receiptContext(post('other', null, 'Max Kellerman on Harden'), undefined, ABBR)).toEqual({ label: 'Post', text: 'Max Kellerman on Harden' })
    expect(receiptContext(post('game_thread', null, 'Game Thread: X vs Y'), undefined, ABBR)).toEqual({ label: 'Game thread', text: 'Game Thread: X vs Y' })
  })

  it('is null when the bridge has no post', () => {
    expect(receiptContext(undefined, undefined, ABBR)).toBeNull()
  })
})

describe('commentDate', () => {
  it('prints the day in UTC', () => {
    expect(commentDate(1778198400)).toBe('May 8, 2026')
  })
})
