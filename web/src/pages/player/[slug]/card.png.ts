// One share card per player, from the same standings as the player page.
import type { APIRoute, InferGetStaticPropsType } from 'astro'

import { buildCard } from '../../../cards'
import { warmMedia } from '../../../cards/assets'
import { playerCard } from '../../../cards/model'
import { getSeason } from '../../../data'
import { playerStandings } from '../../../lib/standings'

export async function getStaticPaths() {
  const { manifest, tables } = await getSeason()
  const { inputs } = playerStandings(tables, manifest.rules.qualified_threshold)
  const abbr = new Map(tables.teams.map((t) => [t.team, t.abbreviation]))
  warmMedia(tables.players.map((p) => p.headshot_url))
  return tables.players.map((player) => {
    const rosterAbbr = player.roster_team ? (abbr.get(player.roster_team) ?? null) : null
    return { params: { slug: player.slug }, props: { card: playerCard(inputs.get(player.attributed_player)!, player, rosterAbbr, manifest.season) } }
  })
}

type Props = InferGetStaticPropsType<typeof getStaticPaths>

export const GET: APIRoute<Props> = async ({ props }) => new Response(await buildCard(props.card), { headers: { 'Content-Type': 'image/png' } })
