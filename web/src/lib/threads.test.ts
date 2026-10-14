import { describe, expect, it } from 'vitest'

import type { PostsRow } from '../data/types.gen'
import { redditCounts } from './threads'

const post = (id: string, type: string, gameId: string | null, n: number): PostsRow => ({
  post_id: id,
  title: id,
  created_utc: 0,
  score: 0,
  num_comments: n,
  link_flair_text: null,
  post_type: type,
  source: null,
  game_id: gameId,
  is_primary: true,
})

describe('redditCounts', () => {
  it('sums both threads of a game and skips a game with one thread or none', () => {
    const posts = [
      post('a', 'game_thread', 'g1', 40_000),
      post('b', 'post_game_thread', 'g1', 13_003),
      post('c', 'post_game_thread', 'g1', 100),
      post('d', 'game_thread', 'g2', 9_000),
      post('e', 'daily', 'g2', 9_000),
      post('f', 'game_thread', null, 9_000),
    ]
    expect(redditCounts(posts)).toEqual(new Map([['g1', 53_103]]))
  })
})
