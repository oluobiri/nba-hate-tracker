// A game's threads are its game thread and its post-game thread together.
// Reddit's count is every comment the two posts carry, and it needs both
// bridged: a lone post would print a partial figure as the whole.
import type { PostsRow } from '../data/types.gen'

export const THREAD_TYPES: ReadonlySet<string> = new Set(['game_thread', 'post_game_thread'])

/** game_id → every comment Reddit counts in its threads; absent unless both threads are bridged. */
export function redditCounts(posts: readonly PostsRow[]): Map<string, number> {
  const bridged = new Map<string, { n: number; types: Set<string> }>()
  for (const p of posts) {
    if (!p.game_id || !THREAD_TYPES.has(p.post_type)) continue
    const b = bridged.get(p.game_id) ?? { n: 0, types: new Set<string>() }
    b.n += p.num_comments
    b.types.add(p.post_type)
    bridged.set(p.game_id, b)
  }
  return new Map([...bridged].flatMap(([id, b]) => (b.types.size === THREAD_TYPES.size ? [[id, b.n] as const] : [])))
}
