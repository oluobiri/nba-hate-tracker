// The leaderboard's share card, and every other page's fallback: the
// official #1 by negative rate with the hero sentence.
import type { APIRoute } from 'astro'

import { buildCard } from '../cards'
import { boardCard } from '../cards/model'
import { getSeason } from '../data'
import { playerStandings } from '../lib/standings'
import { HEADLINE_POPULATION } from '../site'

export const GET: APIRoute = async () => {
  const { manifest, tables } = await getSeason()
  const official = manifest.rules.qualified_threshold
  const { rankings } = playerStandings(tables, official)
  const headshot = new Map(tables.players.map((p) => [p.attributed_player, p.headshot_url]))
  const headline = { count: manifest.corpus[HEADLINE_POPULATION], players: tables.players.length }
  const card = boardCard(rankings.neg, official, headline, (name) => headshot.get(name)!, manifest.season)
  return new Response(await buildCard(card), { headers: { 'Content-Type': 'image/png' } })
}
