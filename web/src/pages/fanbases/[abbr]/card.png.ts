// One share card per fanbase, from the same ranking as the team page.
import type { APIRoute, InferGetStaticPropsType } from 'astro'

import { buildCard } from '../../../cards'
import { warmMedia } from '../../../cards/assets'
import { teamCard } from '../../../cards/model'
import { getSeason } from '../../../data'
import { fanbaseStandings } from '../../../lib/standings'

export async function getStaticPaths() {
  const { manifest, tables } = await getSeason()
  const ranked = fanbaseStandings(tables.fan_team_overall)
  warmMedia(tables.fan_team_overall.map((r) => r.logo_url))
  return ranked.map((r) => {
    const { team, ...counts } = r.row
    return { params: { abbr: team.abbreviation.toLowerCase() }, props: { card: teamCard(team, counts, r.rank!, ranked.length, manifest.season) } }
  })
}

type Props = InferGetStaticPropsType<typeof getStaticPaths>

export const GET: APIRoute<Props> = async ({ props }) => new Response(await buildCard(props.card), { headers: { 'Content-Type': 'image/png' } })
