// One load per build: every page's getStaticPaths and frontmatter share it.
import { CURRENT_SEASON } from '../site'
import { loadSeason, type SeasonData } from './load'

let pending: Promise<SeasonData> | undefined

export function getSeason(): Promise<SeasonData> {
  pending ??= loadSeason(CURRENT_SEASON).then((data) => {
    console.log(`[data] ${data.season} from ${data.source}: ${Object.keys(data.tables).length} tables`)
    for (const w of data.warnings) console.warn(`[data] warning: ${w}`)
    return data
  })
  return pending
}

export type { SeasonData } from './load'
