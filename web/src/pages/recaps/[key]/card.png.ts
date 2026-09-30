// One share card per recap, from the same joins as the recap page.
import type { APIRoute, InferGetStaticPropsType } from 'astro'

import { buildCard } from '../../../cards'
import { warmMedia } from '../../../cards/assets'
import { recapCard } from '../../../cards/model'
import { getSeason } from '../../../data'
import { buildRecaps } from '../../../lib/recaps'

export async function getStaticPaths() {
  const { manifest, tables } = await getSeason()
  const recaps = buildRecaps(manifest, tables)
  warmMedia(recaps.map((r) => r.player.headshot_url))
  return recaps.map((recap) => ({ params: { key: recap.key }, props: { card: recapCard(recap, manifest.season) } }))
}

type Props = InferGetStaticPropsType<typeof getStaticPaths>

export const GET: APIRoute<Props> = async ({ props }) => new Response(await buildCard(props.card), { headers: { 'Content-Type': 'image/png' } })
