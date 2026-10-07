// The pipeline as one drawing: three sources feed five stages on one laptop,
// a publish step under MFA writes the contract to a data bucket behind
// CloudFront, GitHub Actions builds the site from the same public data, and
// fans, share previews and analysts read through CloudFront. Two forms: the
// wide drawing in two rows where the column holds it, a stack below that.
// Every count, model name and registry size arrives as a prop, read at build.
import type { ReactNode } from 'react'

import { fmtInt } from '../lib/format'
import { BrandMark, MARKS, type MarkName } from './BrandMark'

export interface PipelineDiagramProps {
  season: string
  counts: { raw: number; submitted: number; usable: number; attributed: number }
  /** Tracked players in players.yaml. */
  tracked: number
  /** Tables and recap files the manifest registers. */
  tables: number
  recaps: number
  /** Short model names ("Haiku 4.5", "Sonnet 5"). */
  sentimentModel: string
  targetModel: string
  /** The hand check's draw and its scored count. */
  drawn: number
  scored: number
}

// The wide drawing's grid: five stage columns after the sources, one box width.
const COL = [20, 215, 410, 605, 800, 995] as const
const BOX_W = 165
const MARK = 18

interface BoxProps {
  x: number
  y: number
  w: number
  h: number
  title: string
  /** Lines under the title; a line starting with # is a count, drawn in the funnel's colour. */
  lines?: readonly string[]
  mark?: MarkName
  kind?: 'ext' | 'key'
}

function Box({ x, y, w, h, title, lines = [], mark, kind }: BoxProps) {
  return (
    <>
      <rect className={`pipe-box${kind ? ` pipe-box--${kind}` : ''}`} x={x} y={y} width={w} height={h} rx={3} />
      {mark && <MarkAt name={mark} x={x + 10} y={y + 9} />}
      <text className="pipe-t" x={x + (mark ? 34 : 10)} y={y + 23}>
        {title}
      </text>
      {lines.map((l, i) => (
        <text key={i} className={l.startsWith('#') ? 'pipe-n' : 'pipe-m'} x={x + 10} y={y + 38 + 13 * i}>
          {l.replace(/^#/, '')}
        </text>
      ))}
    </>
  )
}

function MarkAt({ name, x, y, size = MARK }: { name: MarkName; x: number; y: number; size?: number }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${size / 24})`}>
      <BrandMarkPath name={name} />
    </g>
  )
}

// The mark's path alone, for use inside the drawing (BrandMark is its own svg).
function BrandMarkPath({ name }: { name: MarkName }) {
  return <path d={MARKS[name].path} fill={MARKS[name].color} />
}

type ArrowKind = 'plain' | 'main' | 'pub'
const Arrow = ({ d, kind = 'plain' }: { d: string; kind?: ArrowKind }) => <path className={`pipe-a pipe-a--${kind}`} d={d} markerEnd={`url(#pipe-ah-${kind})`} />

const Label = ({ x, y, text, kind = 'plain', anchor = 'middle' }: { x: number; y: number; text: string; kind?: 'plain' | 'sm' | 'pub'; anchor?: 'start' | 'middle' | 'end' }) => (
  <text className={`pipe-l pipe-l--${kind}`} x={x} y={y} textAnchor={anchor}>
    {text}
  </text>
)

const Zone = ({ x, name, sub }: { x: number; name: string; sub: string }) => (
  <>
    <text className="pipe-zh" x={x + 82} y={88} textAnchor="middle">
      {name}
    </text>
    <text className="pipe-zm" x={x + 82} y={102} textAnchor="middle">
      {sub}
    </text>
  </>
)

function Wide(p: PipelineDiagramProps) {
  const { counts: c } = p
  const bands: [string, string[]][] = [
    ['CONFIG', ['Players, teams, season and the curation in YAML', 'each version stamped on what it shaped']],
    ['CONTRACT', ['One schema module renders schema.json', 'the site generates its types from it']],
    ['CHECKED', ['Tests on every change, both classifiers evaluated', `${fmtInt(p.drawn)} drawn, ${fmtInt(p.scored)} scored by hand`]],
    ['ACCESS', ['Private buckets, read through CloudFront', 'publish needs MFA; deploy needs a merge']],
  ]
  return (
    <svg className="pipe__wide" viewBox="0 0 1180 700" aria-hidden="true">
      <defs>
        {(['plain', 'main', 'pub'] as const).map((k) => (
          <marker key={k} id={`pipe-ah-${k}`} className={`pipe-ah pipe-ah--${k}`} viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto-start-reverse">
            <path d="M0,0 L8,4 L0,8 z" />
          </marker>
        ))}
      </defs>
      <text className="pipe-ph" x={20} y={64}>
        SOURCES
      </text>
      <rect className="pipe-panel" x={205} y={44} width={960} height={300} rx={4} />
      <text className="pipe-ph" x={220} y={64}>
        ON ONE LAPTOP
      </text>
      <text className="pipe-pm" x={340} y={64}>
        one command per stage, run by hand
      </text>
      <Zone x={COL[1]} name="LANDING" sub="raw/ reference/ media/" />
      <Zone x={COL[2]} name="CLEAN" sub="filtered/" />
      <Zone x={COL[3]} name="ENRICHMENT" sub="batches/" />
      <Zone x={COL[4]} name="CURATED" sub="processed/" />
      <Zone x={COL[5]} name="PRESENTATION" sub="dashboard/" />
      {[2, 3, 4, 5].map((i) => (
        <line key={i} className="pipe-sep" x1={COL[i]! - 15} y1={76} x2={COL[i]! - 15} y2={334} />
      ))}

      <Box x={COL[0]} y={116} w={BOX_W} h={64} title="r/NBA" lines={['Arctic Shift', 'comments and posts']} mark="reddit" />
      <Box x={COL[0]} y={196} w={BOX_W} h={50} title="stats.nba.com" lines={['rosters · game logs']} mark="nba" />
      <Box x={COL[0]} y={262} w={BOX_W} h={64} title="cdn.nba.com" lines={['play-by-play', 'headshots · logos']} mark="nba" />
      <Box x={COL[1]} y={116} w={BOX_W} h={64} title="Comments" lines={['one line each', `#${fmtInt(c.raw)}`]} />
      <Box x={COL[1]} y={196} w={BOX_W} h={50} title="Posts" lines={['game threads, the rest']} />
      <Box x={COL[1]} y={262} w={BOX_W} h={64} title="Reference and media" lines={['snapshots as fetched', 'never classified']} />
      <Box x={COL[2]} y={116} w={BOX_W} h={64} title="Find names" lines={[`${fmtInt(p.tracked)} players, every name`, `#${fmtInt(c.submitted)} kept`]} mark="polars" />
      <Box x={COL[3]} y={116} w={BOX_W} h={64} title="Read the sentiment" lines={[p.sentimentModel, `#${fmtInt(c.usable)} usable`]} mark="claude" />
      <Box x={COL[3]} y={196} w={BOX_W} h={50} title="Check the target" lines={[`${p.targetModel} · quotes only`]} mark="claude" />
      <Box x={COL[4]} y={116} w={BOX_W} h={64} title="The fact" lines={['one row per comment', `#${fmtInt(c.attributed)} counted`]} />
      <Box x={COL[4]} y={196} w={BOX_W} h={50} title="Verdicts" lines={['who each quote is about']} />
      <Box x={COL[4]} y={262} w={BOX_W} h={50} title="Posts to games" lines={['thread → game']} />
      <Box x={COL[5]} y={116} w={BOX_W} h={196} title="The contract" lines={[`${fmtInt(p.tables)} tables`, `${fmtInt(p.recaps)} recap files`, 'manifest.json', 'schema.json', '', 'built by one aggregate', 'step, pre-flighted']} mark="parquet" kind="key" />
      <Box x={COL[3] + 20} y={4} w={240} h={30} title="Anthropic Batch API" mark="claude" kind="ext" />

      <Arrow d={`M${COL[0] + BOX_W},148 H${COL[1] - 2}`} />
      <Arrow d={`M${COL[0] + BOX_W},221 H${COL[0] + 180} V294 H${COL[1] - 2}`} />
      <Arrow d={`M${COL[0] + BOX_W},294 H${COL[1] - 2}`} />
      <Arrow d={`M${COL[1] + BOX_W},148 H${COL[2] - 2}`} kind="main" />
      <Arrow d={`M${COL[2] + BOX_W},148 H${COL[3] - 2}`} kind="main" />
      <Arrow d={`M${COL[3] + BOX_W},148 H${COL[4] - 2}`} kind="main" />
      <Arrow d={`M${COL[4] + BOX_W},148 H${COL[5] - 2}`} kind="main" />
      <Arrow d={`M${COL[3] + 12},34 V114`} />
      <Arrow d={`M${COL[3] + 153},116 V36`} />
      <Label x={COL[3] + 18} y={70} text="requests" kind="sm" anchor="start" />
      <Label x={COL[3] + 147} y={70} text="answers" kind="sm" anchor="end" />
      <Arrow d={`M${COL[4] + 82},180 V188 H${COL[3] + 82} V194`} />
      <Label x={COL[4] - 15} y={191} text="quote candidates" kind="sm" />
      <Arrow d={`M${COL[3] + BOX_W},221 H${COL[4] - 2}`} />
      <Arrow d={`M${COL[4] + BOX_W},221 H${COL[5] - 2}`} />
      <Arrow d={`M${COL[1] + BOX_W},221 H400 V287 H${COL[4] - 2}`} />
      <Label x={COL[2] + 110} y={282} text="matched to games" kind="sm" />
      <Arrow d={`M${COL[1] + 82},326 V336 H${COL[5] + 40} V314`} />
      <Label x={COL[3] + 82} y={331} text="joined at the end, never classified" kind="sm" />
      <Arrow d={`M${COL[4] + BOX_W},287 H${COL[5] - 2}`} />

      <rect className="pipe-panel pipe-panel--aws" x={205} y={384} width={590} height={200} rx={4} />
      <MarkAt name="aws" x={220} y={391} />
      <text className="pipe-ph" x={244} y={405}>
        ON AWS
      </text>
      <text className="pipe-ph" x={840} y={405}>
        WHO READS IT
      </text>
      <Box x={220} y={420} w={170} h={64} title="Data bucket" lines={[`season=${p.season}/ · media/`, 'private, versioned']} mark="s3" />
      <Box x={420} y={420} w={170} h={64} title="CloudFront" lines={['courtsentiment.com', '/ · /data/* · /media/*']} mark="aws" />
      <Box x={620} y={420} w={160} h={64} title="Site bucket" lines={['the built pages']} mark="s3" />
      <Box x={620} y={510} w={160} h={50} title="GitHub Actions" lines={['builds on merge, deploys']} mark="actions" kind="ext" />
      <Box x={220} y={510} w={170} h={50} title="Route 53" lines={['the name → CloudFront']} mark="route53" />
      <Arrow d={`M${COL[5] + 120},312 V360 H305 V418`} kind="pub" />
      <Label x={640} y={356} text="publish · MFA, pre-flighted against the contract" kind="pub" />
      <Arrow d={`M${COL[1] + 40},326 V418`} kind="pub" />
      <Label x={COL[1] + 34} y={380} text="media" kind="pub" anchor="end" />
      <Arrow d="M390,452 H418" />
      <Label x={404} y={446} text="OAC" kind="sm" />
      <Arrow d="M620,452 H592" />
      <Arrow d="M700,510 V486" />
      <Label x={708} y={500} text="deploy · OIDC" kind="sm" anchor="start" />
      <Arrow d="M620,535 H505 V486" />
      <Label x={612} y={549} text="reads the same public /data" kind="pub" anchor="end" />
      <Arrow d="M305,510 V486" />
      <Box x={840} y={420} w={170} h={44} title="Fans" lines={['the site, phone first']} />
      <Box x={840} y={476} w={170} h={44} title="Share previews" lines={['cards baked at build']} />
      <Box x={840} y={532} w={170} h={44} title="Analysts" lines={['DuckDB on the public URLs']} mark="duckdb" />
      <Arrow d="M505,420 V396 H812 V442 H838" />
      <Arrow d="M812,442 V498 H838" />
      <Arrow d="M812,498 V554 H838" />

      <text className="pipe-pm" x={20} y={618}>
        UNDER EVERY STAGE
      </text>
      {bands.map(([h, ls], i) => (
        <g key={h}>
          <rect className="pipe-band" x={20 + 290 * i} y={628} width={275} height={62} rx={3} />
          <text className="pipe-bh" x={32 + 290 * i} y={648}>
            {h}
          </text>
          {ls.map((l, j) => (
            <text key={j} className="pipe-bt" x={32 + 290 * i} y={666 + 14 * j}>
              {l}
            </text>
          ))}
        </g>
      ))}
    </svg>
  )
}

interface Item {
  mark?: MarkName
  title: string
  sub: string
  count?: string
}

const Section = ({ name, fold, items, kind }: { name: string; fold?: string; items: Item[]; kind?: 'aws' }) => (
  <section className={`pipe-sec${kind ? ` pipe-sec--${kind}` : ''}`}>
    <header className="pipe-sec__head">
      <span className="pipe-sec__name">{name}</span>
      {fold && <span className="pipe-sec__fold">{fold}</span>}
    </header>
    {items.map((it) => (
      <div key={it.title} className="pipe-item">
        {it.mark ? <BrandMark name={it.mark} className="pipe-item__mark" /> : <span className="pipe-item__mark" />}
        <div>
          <span className="pipe-item__title">{it.title}</span>
          <span className="pipe-item__sub">{it.sub}</span>
        </div>
        {it.count && <span className="pipe-item__count">{it.count}</span>}
      </div>
    ))}
  </section>
)

const Hop = ({ text, kind = 'plain' }: { text: string; kind?: ArrowKind }) => (
  <div className={`pipe-hop pipe-hop--${kind}`}>
    <span aria-hidden="true">↓</span>
    {text}
  </div>
)

function Stacked(p: PipelineDiagramProps) {
  const { counts: c } = p
  return (
    <div className="pipe__stack" aria-hidden="true">
      <Section
        name="Sources"
        items={[
          { mark: 'reddit', title: 'r/NBA', sub: 'Arctic Shift · comments and posts' },
          { mark: 'nba', title: 'stats.nba.com', sub: 'rosters · game logs' },
          { mark: 'nba', title: 'cdn.nba.com', sub: 'play-by-play · headshots · logos' },
        ]}
      />
      <Hop text="download" />
      <Section
        name="Landing"
        fold="raw/ reference/ media/"
        items={[
          { title: 'Comments', sub: 'one line each', count: fmtInt(c.raw) },
          { title: 'Posts, reference, media', sub: 'held for later stages' },
        ]}
      />
      <Hop text="find names" kind="main" />
      <Section name="Clean" fold="filtered/" items={[{ mark: 'polars', title: 'Name a tracked player', sub: `${fmtInt(p.tracked)} players`, count: fmtInt(c.submitted) }]} />
      <Hop text="batch requests ⇄ Anthropic Batch API" kind="main" />
      <Section
        name="Enrichment"
        fold="batches/"
        items={[
          { mark: 'claude', title: 'Read the sentiment', sub: p.sentimentModel, count: fmtInt(c.usable) },
          { mark: 'claude', title: 'Check the target', sub: `${p.targetModel} · quotes only` },
        ]}
      />
      <Hop text="pick the player" kind="main" />
      <Section
        name="Curated"
        fold="processed/"
        items={[
          { title: 'The fact', sub: 'one row per comment', count: fmtInt(c.attributed) },
          { title: 'Verdicts · posts to games', sub: 'who each quote is about · thread → game' },
        ]}
      />
      <Hop text="aggregate, joining the reference" />
      <Section name="Presentation" fold="dashboard/" items={[{ mark: 'parquet', title: 'The contract', sub: `${fmtInt(p.tables)} tables · ${fmtInt(p.recaps)} recaps · manifest · schema` }]} />
      <Hop text="publish · MFA · pre-flighted" kind="pub" />
      <Section
        name="On AWS"
        kind="aws"
        items={[
          { mark: 's3', title: 'Data bucket', sub: `season=${p.season}/ · media/` },
          { mark: 'aws', title: 'CloudFront', sub: 'courtsentiment.com' },
          { mark: 'actions', title: 'GitHub Actions', sub: 'reads /data, builds, deploys the site bucket' },
        ]}
      />
      <Hop text="serve" />
      <Section
        name="Who reads it"
        items={[
          { title: 'Fans', sub: 'the site, phone first' },
          { title: 'Share previews', sub: 'cards baked at build' },
          { mark: 'duckdb', title: 'Analysts', sub: 'DuckDB on the public URLs' },
        ]}
      />
      <section className="pipe-sec pipe-sec--under">
        <header className="pipe-sec__head">
          <span className="pipe-sec__name">Under every stage</span>
        </header>
        <p>
          <b>Config</b> in YAML, versions stamped · <b>Contract</b> one schema, the site's types from it · <b>Checked</b> tests, both classifiers evaluated, {fmtInt(p.scored)} by hand · <b>Access</b> MFA to publish, a merge to deploy
        </p>
      </section>
    </div>
  )
}

/** The pipeline in two forms; the figure around it carries the caption. */
export function PipelineDiagram(p: PipelineDiagramProps): ReactNode {
  const spoken = `The pipeline. Three sources feed five stages on one laptop: landing, clean, enrichment with two classifier passes, curated and presentation. ${fmtInt(p.counts.raw)} comments downloaded, ${fmtInt(p.counts.submitted)} name a tracked player, ${fmtInt(p.counts.usable)} get a usable answer, ${fmtInt(p.counts.attributed)} count for one player. A publish step under MFA writes the contract to a data bucket behind CloudFront. GitHub Actions builds the site from the same public data. Fans, share previews and analysts read through CloudFront.`
  return (
    <div className="pipe" role="img" aria-label={spoken}>
      <Wide {...p} />
      <Stacked {...p} />
    </div>
  )
}
