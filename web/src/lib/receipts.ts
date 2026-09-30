// A receipt's context: the thread it lived in as one line, and its date.
// Game threads read as the game (score, round, day); any other post as
// its title. comment_samples carries no author, so the flair is the only
// thing said about the commenter.
import type { GamesRow, PostsRow } from '../data/types.gen'
import { scoreLine } from './games'
import { weekLabel } from './weeks'

export interface ReceiptContext {
  /** "Game thread" · "Post-game thread" · "Post". */
  label: string
  text: string
}

const LABEL: Record<string, string> = { game_thread: 'Game thread', post_game_thread: 'Post-game thread' }

/** The post a receipt lived in, as a label and one line; null when the bridge has no row. */
export function receiptContext(post: PostsRow | undefined, game: GamesRow | undefined, abbr: ReadonlyMap<string, string>): ReceiptContext | null {
  if (!post) return null
  const label = LABEL[post.post_type] ?? 'Post'
  if (!game || !LABEL[post.post_type]) return { label, text: post.title }
  const round = game.playoff_round && game.playoff_game ? ` · R${game.playoff_round} G${game.playoff_game}` : ''
  return { label, text: `${scoreLine(game, abbr)}${round} · ${weekLabel(game.game_date)}` }
}

/** "May 8, 2026" from epoch seconds, in UTC. */
export function commentDate(epoch: number): string {
  return new Date(epoch * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
}
