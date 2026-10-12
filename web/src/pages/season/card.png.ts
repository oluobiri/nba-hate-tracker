// The season's share card: the page's lede over the whole population's split.
import type { APIRoute } from 'astro'

import { buildCard } from '../../cards'
import { seasonCard } from '../../cards/model'
import { getSeason } from '../../data'
import { sumCounts } from '../../lib/metrics'
import { buildSeason, ledeText } from '../../lib/season'
import { HARSHEST_NOTE } from '../../lib/season-copy'
import { HEADLINE_POPULATION } from '../../site'

export const GET: APIRoute = async () => {
  const { manifest, tables } = await getSeason()
  const season = buildSeason({ manifest, tables }, HARSHEST_NOTE)
  const headline = { count: manifest.corpus[HEADLINE_POPULATION], players: tables.players.length }
  const card = seasonCard(ledeText(season.lede), sumCounts(season.nights.map((n) => n.counts)), headline, manifest.season)
  return new Response(await buildCard(card), { headers: { 'Content-Type': 'image/png' } })
}
