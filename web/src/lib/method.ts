// How a comment becomes a row, told from the published figures: the stage
// counts and what drops between them, the names the finder marked in a body,
// the request as it went out and the answer as it came back.
import type { ClassifierIdentity, Corpus, MethodExamplesRow } from '../data/types.gen'
import type { Sentiment } from './types'

/** Requests leave in batches of this many: a fact about the process, never a rule of the data. */
export const BATCH_SIZE = 100_000

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
