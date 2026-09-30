// The recap file, re-served by the site so the replay island can fetch it
// same-origin in every environment (the walk runs on localhost, the data
// host sends no CORS). Read from the data base at build like the cards read
// media, asserted against the contract, and identified against the registry.
import type { APIRoute, InferGetStaticPropsType } from 'astro'

import { getSeason } from '../../../data'
import { readJson, seasonLocation } from '../../../data/env'
import { assertRecapDocument, assertRecapIdentity } from '../../../data/recap'
import { buildRecaps } from '../../../lib/recaps'

export async function getStaticPaths() {
  const { manifest, tables } = await getSeason()
  return buildRecaps(manifest, tables).map((recap) => ({
    params: { key: recap.key },
    props: { key: recap.key, entry: recap.entry, season: manifest.season },
  }))
}

type Props = InferGetStaticPropsType<typeof getStaticPaths>

export const GET: APIRoute<Props> = async ({ props }) => {
  const { key, entry, season } = props
  const doc = assertRecapDocument(await readJson(seasonLocation(season), entry.file), entry.file)
  assertRecapIdentity(doc, key, entry, season)
  return new Response(JSON.stringify(doc), { headers: { 'Content-Type': 'application/json' } })
}
