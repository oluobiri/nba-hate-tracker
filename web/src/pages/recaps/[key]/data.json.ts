// The recap file, re-served by the site so the replay island can fetch it
// same-origin in every environment (the walk runs on localhost, the data
// host sends no CORS). Read from the data base at build like the cards read
// media, asserted against the contract, and identified against the registry.
import type { APIRoute, InferGetStaticPropsType } from 'astro'

import { getSeason } from '../../../data'
import { ContractError } from '../../../data/contract'
import { readJson, seasonLocation } from '../../../data/env'
import { assertRecapDocument, assertRecapIdentity } from '../../../data/recap'
import type { RecapDocument, RecapEntry } from '../../../data/types.gen'
import { buildTimeline } from '../../../lib/clock'
import { buildRecaps } from '../../../lib/recaps'
import { buildRoom, prepareComments, recapRows, roomByPeriod } from '../../../lib/replay'

export async function getStaticPaths() {
  const { manifest, tables } = await getSeason()
  return buildRecaps(manifest, tables).map((recap) => ({
    params: { key: recap.key },
    props: { key: recap.key, entry: recap.entry, season: manifest.season },
  }))
}

type Props = InferGetStaticPropsType<typeof getStaticPaths>

// The page's own reading of the file at the final buzzer must reproduce the
// registry's per-period counts: the one cross-check between the two.
function assertPeriods(doc: RecapDocument, entry: RecapEntry): void {
  const rows = recapRows(doc)
  const tl = buildTimeline(rows.periods)
  const room = buildRoom(prepareComments(rows.comments, tl, {}), tl)
  for (const cell of roomByPeriod(room, room.comments.length)) {
    const want = entry.by_period[String(cell.key)]
    const { neg, neu, pos } = cell.counts
    if (!want || want.neg !== neg || want.neu !== neu || want.pos !== pos)
      throw new ContractError(`${entry.file}: ${cell.label} reads ${neg}/${neu}/${pos} from the file, the registry says ${JSON.stringify(want)}`)
  }
}

export const GET: APIRoute<Props> = async ({ props }) => {
  const { key, entry, season } = props
  const doc = assertRecapDocument(await readJson(seasonLocation(season), entry.file), entry.file)
  assertRecapIdentity(doc, key, entry, season)
  assertPeriods(doc, entry)
  return new Response(JSON.stringify(doc), { headers: { 'Content-Type': 'application/json' } })
}
