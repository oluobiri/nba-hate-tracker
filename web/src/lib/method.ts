// How a comment becomes a row, told from the published figures: the stage
// counts and what drops between them, the names the finder marked in a body,
// the request as it went out and the answer as it came back; then the pair
// that shows why four metrics, the hand check's gaps on a Δ axis, and the
// copy join that fails the build when the examples and their lines disagree.
import type { ClassifierIdentity, ClassMix, Corpus, MethodExamplesRow } from '../data/types.gen'
import { negRate, posRate } from './metrics'
import { type Counts, type Sentiment, SENTIMENTS } from './types'

/** Requests leave in batches of this many: a fact about the process, never a rule of the data. */
export const BATCH_SIZE = 100_000
/** Two players are "praised at nearly the same rate" within this many points of positive rate. */
export const PAIR_POS_TOLERANCE = 0.01
/** Padding past the widest range on the gap chart's axis. */
export const GAP_AXIS_PAD = 1.15
/** The ticks the gap chart may show, in points; those inside the domain are drawn. */
export const GAP_TICKS: readonly number[] = [-0.1, -0.05, 0, 0.05, 0.1]
/** The attribution cases in the order the table tells them. */
export const CASE_ORDER: readonly string[] = ['one_name', 'one_name_other_pick', 'several_resolved', 'several_no_pick', 'several_resolved_unlisted', 'several_unresolved']

export interface StageDrops {
  /** Downloaded comments that name no tracked player. */
  find: number
  /** Submitted comments with no usable answer. */
  answer: number
  /** Usable comments that count for nobody. */
  pick: number
}

/** What drops out between the corpus figures; the page never types a drop. */
export function stageDrops(corpus: Corpus): StageDrops {
  const { raw_comments: raw, population_submitted: submitted, usable, attributed } = corpus
  if (raw === null || submitted === null) throw new Error('corpus: raw_comments and population_submitted are needed for the walkthrough')
  return { find: raw - submitted, answer: submitted - usable, pick: usable - attributed }
}

/** A stage count as a share of the downloaded total, for its proportion bar. */
export const stageShare = (n: number, total: number): number => (total > 0 ? Math.max(0, Math.min(1, n / total)) : 0)

export interface Segment {
  text: string
  mark: boolean
}

const isWord = (ch: string | undefined): boolean => ch !== undefined && /\w/.test(ch)

/** The first whole-word occurrence of `name` in `body`, or -1. */
function firstWholeWord(body: string, name: string): number {
  if (name === '') return -1
  let from = 0
  while (from <= body.length) {
    const at = body.indexOf(name, from)
    if (at === -1) return -1
    if (!isWord(body[at - 1]) && !isWord(body[at + name.length])) return at
    from = at + 1
  }
  return -1
}

/**
 * The body split around the finder's matches: one mark per name, the first
 * whole-word hit, as the body spells it. A name the body does not carry marks
 * nothing; overlapping hits keep the earlier one.
 */
export function markNames(body: string, names: readonly string[]): Segment[] {
  const hits = names
    .map((n) => ({ start: firstWholeWord(body, n), end: firstWholeWord(body, n) + n.length }))
    .filter((h) => h.start >= 0)
    .toSorted((a, b) => a.start - b.start)
  const out: Segment[] = []
  let cursor = 0
  for (const h of hits) {
    if (h.start < cursor) continue
    if (h.start > cursor) out.push({ text: body.slice(cursor, h.start), mark: false })
    out.push({ text: body.slice(h.start, h.end), mark: true })
    cursor = h.end
  }
  if (cursor < body.length || out.length === 0) out.push({ text: body.slice(cursor), mark: false })
  return out
}

/** A prompt template with its `{slot}` values filled and its `{{ }}` braces unescaped. */
export function fillPrompt(template: string, vars: Readonly<Record<string, string>>): string {
  let out = template.replaceAll('{{', '\u0000').replaceAll('}}', '\u0001')
  for (const [k, v] of Object.entries(vars)) out = out.replaceAll(`{${k}}`, v)
  return out.replaceAll('\u0000', '{').replaceAll('\u0001', '}')
}

export interface BatchRequest {
  custom_id: string
  params: Record<string, unknown>
}

/** The Batch API request for one comment, rebuilt from the manifest's classifier block. */
export function buildRequest(row: Pick<MethodExamplesRow, 'comment_id' | 'body'>, classifier: ClassifierIdentity): BatchRequest {
  if (classifier.prompt === null || classifier.max_tokens === null)
    throw new Error(`classifier ${classifier.model}: the manifest carries no prompt or max_tokens to rebuild a request from`)
  return {
    custom_id: row.comment_id,
    params: {
      model: classifier.model,
      max_tokens: classifier.max_tokens,
      ...classifier.sampling_params,
      messages: [{ role: 'user', content: fillPrompt(classifier.prompt, { comment_body: row.body }) }],
    },
  }
}

export interface Answer {
  s: Sentiment
  c: number
  p: string | null
}

/** The three keys as the classifier returned them. */
export const answerOf = (row: Pick<MethodExamplesRow, 'sentiment' | 'confidence' | 'sentiment_player'>): Answer => ({
  s: row.sentiment as Sentiment,
  c: row.confidence,
  p: row.sentiment_player,
})

/** The fields of the raw record the table carries; the author is never among them. */
export const rawRecord = (row: MethodExamplesRow): Record<string, unknown> => ({
  id: row.comment_id,
  body: row.body,
  author_flair_text: row.author_flair_text,
  score: row.score,
  link_id: row.link_id,
})

/** The fact's row for one comment, the columns the page names. */
export const rowRecord = (row: MethodExamplesRow): Record<string, unknown> => ({
  comment_id: row.comment_id,
  mentioned_players: row.mentioned_players,
  mentioned_text: row.mentioned_text,
  sentiment: row.sentiment,
  confidence: row.confidence,
  sentiment_player: row.sentiment_player,
  attributed_player: row.attributed_player,
  fan_team: row.fan_team,
  score: row.score,
})

/** A positive or negative answer at or above the quote floor may be quoted; a neutral one never is. */
export const isQuotable = (row: Pick<MethodExamplesRow, 'sentiment' | 'confidence'>, minConfidence: number): boolean =>
  row.sentiment !== 'neu' && row.confidence >= minConfidence

/** The rows of one slot in their curated order. */
export const bySlot = (rows: readonly MethodExamplesRow[], slot: string): MethodExamplesRow[] =>
  rows.filter((r) => r.slot === slot).toSorted((a, b) => a.position - b.position)

/** The one comment the walkthrough follows. */
export function requireTrace(rows: readonly MethodExamplesRow[]): MethodExamplesRow {
  const traces = bySlot(rows, 'trace')
  if (traces.length !== 1) throw new Error(`method_examples: ${traces.length} trace rows, the walkthrough needs exactly one`)
  return traces[0]!
}

/**
 * The two ranked players praised at nearly the same rate whose negative rates
 * are furthest apart: the same praise, a different conversation around it.
 * Harsher first. Null when no two players are that close.
 */
export function metricsPair<T extends Counts>(rows: readonly T[], official: number): [T, T] | null {
  const ranked = rows.filter((r) => r.total >= official)
  let best: [T, T] | null = null
  let widest = -1
  for (let i = 0; i < ranked.length; i++) {
    for (let j = i + 1; j < ranked.length; j++) {
      const a = ranked[i]!
      const b = ranked[j]!
      if (Math.abs(posRate(a) - posRate(b)) > PAIR_POS_TOLERANCE) continue
      const gap = Math.abs(negRate(a) - negRate(b))
      if (gap > widest) {
        widest = gap
        best = negRate(a) >= negRate(b) ? [a, b] : [b, a]
      }
    }
  }
  return best
}

export type GapCall = 'within' | 'outside'

export interface GapRow {
  cls: Sentiment
  /** Classifier share minus manual share, a fraction. */
  gap: number
  /** Half the 95% interval, a fraction. */
  margin: number
  /** Whether the range crosses zero: the wording is chosen here, never typed. */
  call: GapCall
}

/** The hand check's per-class gaps in display order; a block with a hole fails the build. */
export function gapRows(classMix: Record<string, ClassMix> | null): GapRow[] {
  if (classMix === null) throw new Error('rules.accuracy.class_mix: absent, the hand check cannot be drawn')
  return SENTIMENTS.map((cls) => {
    const m = classMix[cls]
    if (!m || m.gap === null || m.gap_margin === null) throw new Error(`rules.accuracy.class_mix.${cls}: gap or gap_margin missing`)
    return { cls, gap: m.gap, margin: m.gap_margin, call: Math.abs(m.gap) <= m.gap_margin ? 'within' : 'outside' }
  })
}

/** A symmetric Δ domain holding every range, padded. */
export function gapDomain(rows: readonly GapRow[], pad: number = GAP_AXIS_PAD): [number, number] {
  const lim = Math.max(...rows.map((r) => Math.abs(r.gap) + r.margin)) * pad
  return [-lim, lim]
}

/** The ticks inside the domain. */
export const gapTicks = (domain: readonly [number, number]): number[] => GAP_TICKS.filter((t) => t >= domain[0] && t <= domain[1])

/** "claude-haiku-4-5-20251001" → "Haiku 4.5"; "claude-sonnet-5" → "Sonnet 5". */
export function shortModel(id: string): string {
  const tokens = id
    .replace(/^claude-/, '')
    .replace(/-\d{8}$/, '')
    .split('-')
  const words: string[] = []
  for (const t of tokens) {
    const last = words.at(-1)
    if (/^\d+$/.test(t) && last !== undefined && /^\d+(\.\d+)*$/.test(last)) words[words.length - 1] = `${last}.${t}`
    else words.push(t)
  }
  return words.map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w)).join(' ')
}

export class MethodCopyError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'MethodCopyError'
  }
}

/**
 * The page's lines joined to the rows they are about. A row without a line
 * or a line without a row fails the build, naming each.
 */
export function joinCopy<T>(keys: readonly string[], copy: Readonly<Record<string, T>>, what: string): Map<string, T> {
  const wanted = new Set(keys)
  const missing = [...wanted].filter((k) => !(k in copy))
  const orphans = Object.keys(copy).filter((k) => !wanted.has(k))
  if (missing.length || orphans.length) {
    const parts = []
    if (missing.length) parts.push(`no copy for ${missing.join(', ')}`)
    if (orphans.length) parts.push(`copy with no row: ${orphans.join(', ')}`)
    throw new MethodCopyError(`${what}: ${parts.join('; ')}`)
  }
  return new Map([...wanted].map((k) => [k, copy[k] as T]))
}

/** The case rows and the trace, one per attribution case, in the table's order. */
export function caseRows(rows: readonly MethodExamplesRow[]): MethodExamplesRow[] {
  const picked = [...bySlot(rows, 'case'), requireTrace(rows)]
  for (const r of picked) {
    if (!CASE_ORDER.includes(r.attribution_case)) throw new Error(`method_examples: ${r.comment_id} has an unknown attribution_case ${r.attribution_case}`)
  }
  return picked.toSorted((a, b) => CASE_ORDER.indexOf(a.attribution_case) - CASE_ORDER.indexOf(b.attribution_case))
}
