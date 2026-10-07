// The three ledgers of How a comment is read: every case the attribution
// rule can produce, where the classifier slips against a hand label, and
// the quote check. Each row is a method_examples row with its line of copy.
import type { MethodExamplesRow } from '../data/types.gen'
import { fmtInt } from '../lib/format'
import { type HandLabel, answerOf } from '../lib/method'
import { commentDate } from '../lib/receipts'
import type { Sentiment } from '../lib/types'
import { Answer } from './Answer'
import { MarkedBody, commentUrl } from './Exhibit'
import { Chips, Ledger, type LedgerColumn, SourceLine } from './Ledger'
import { Stamp } from './Stamp'

const SENTIMENT: Record<Sentiment, string> = { neg: 'negative', neu: 'neutral', pos: 'positive' }

interface Quoted {
  row: MethodExamplesRow
  /** Why this comment is on the page. */
  note: string
}

/** The body, marked, with its source line and the line of copy. */
function Comment({ row, note }: Quoted) {
  return (
    <>
      <q className="ledger__q">
        <MarkedBody body={row.body} marks={row.mentioned_text} />
      </q>
      <SourceLine date={commentDate(row.created_utc)} score={row.score} url={commentUrl(row.link_id, row.comment_id)} />
      <p className="why">{note}</p>
    </>
  )
}

const Pick = ({ p }: { p: string | null }) => (p === null ? <code className="ans ans__null">null</code> : <code className="ans">"{p}"</code>)

const CountsFor = ({ player }: { player: string | null }) => (player ? <b>{player}</b> : <span className="nobody">Nobody</span>)

export interface CaseRow extends Quoted {
  title: string
}

export interface CaseTableProps {
  rows: readonly CaseRow[]
  /** Downloaded comments that named no tracked player: the first row, never classified. */
  neverClassified: number
}

type CaseLine = { kind: 'none'; count: number } | ({ kind: 'case' } & CaseRow)

// Column sets live at module scope: a cell renderer is not a component made during render.
const CASE_COLUMNS: readonly LedgerColumn<CaseLine>[] = [
  { head: 'Case', rowHead: true, cell: (l) => (l.kind === 'none' ? 'No tracked name' : l.title) },
  {
    head: 'Comment',
    body: true,
    cell: (l) => (l.kind === 'none' ? <span className="muted">{fmtInt(l.count)} downloaded comments, plus the deleted and removed ones.</span> : <Comment row={l.row} note={l.note} />),
  },
  { head: 'Names found', cell: (l) => (l.kind === 'none' ? <span className="muted">none</span> : <Chips names={l.row.mentioned_players} />) },
  { head: "Classifier's p", cell: (l) => (l.kind === 'none' ? <span className="muted">never asked</span> : <Pick p={l.row.sentiment_player} />) },
  { head: 'Counts for', cell: (l) => (l.kind === 'none' ? <span className="nobody">Never classified</span> : <CountsFor player={l.row.attributed_player} />) },
]

/** One row per attribution case, the never-classified comments first. */
export function CaseTable({ rows, neverClassified }: CaseTableProps) {
  const lines: CaseLine[] = [{ kind: 'none', count: neverClassified }, ...rows.map((r) => ({ kind: 'case' as const, ...r }))]
  return <Ledger<CaseLine> caption="Every case the attribution rule can produce" keyOf={(l) => (l.kind === 'none' ? 'none' : l.row.comment_id)} rows={lines} columns={CASE_COLUMNS} />
}

export interface SlipRow extends Quoted {
  label: HandLabel
}

const SLIP_COLUMNS: readonly LedgerColumn<SlipRow>[] = [
  { head: 'Comment', body: true, cell: (q) => <Comment row={q.row} note="" /> },
  {
    head: 'The answer',
    cell: (q) => (
      <>
        <Answer {...answerOf(q.row)} />
        <span className="src">counts for {q.row.attributed_player ?? 'nobody'}</span>
      </>
    ),
  },
  {
    head: 'Read by hand',
    cell: (q) => (
      <span className="meant">
        <Stamp kind="checked" />
        <span>
          <span className={`v-${q.label.sentiment}`}>{SENTIMENT[q.label.sentiment]}</span> · {q.label.target ?? 'nobody'}
        </span>
      </span>
    ),
  },
  { head: 'What happened', cell: (q) => <p className="why why--lead">{q.note}</p> },
]

/** Three answers a careful read disagrees with: the answer beside the hand label. */
export function SlipTable({ rows }: { rows: readonly SlipRow[] }) {
  return <Ledger<SlipRow> caption="Where the classifier slips: the answer beside the hand label" keyOf={(q) => q.row.comment_id} rows={rows} columns={SLIP_COLUMNS} />
}

export interface QuoteCheckRow extends Quoted {
  /** The attribution case, as the case table titles it. */
  caseTitle: string
}

const QUOTE_COLUMNS: readonly LedgerColumn<QuoteCheckRow>[] = [
  { head: 'Comment', body: true, cell: (q) => <Comment row={q.row} note="" /> },
  { head: 'The answer', cell: (q) => <Answer {...answerOf(q.row)} /> },
  {
    head: 'Counts for',
    cell: (q) => (
      <>
        <b>{q.row.attributed_player ?? 'nobody'}</b>
        <span className="src">{q.caseTitle.toLowerCase()}</span>
      </>
    ),
  },
  {
    head: 'The check says',
    cell: (q) => (
      <>
        <span className="verdict">{q.row.verified_target === null ? 'Not a player' : `Not him: ${q.row.verified_target}`}</span> · not quoted
        <p className="why">{q.note}</p>
      </>
    ),
  },
]

/** Two comments that passed every rule and still are not quoted: who the verifier named. */
export function QuoteCheckTable({ rows }: { rows: readonly QuoteCheckRow[] }) {
  return <Ledger<QuoteCheckRow> caption="Before a comment is quoted: the verifier's answer" keyOf={(q) => q.row.comment_id} rows={rows} columns={QUOTE_COLUMNS} />
}
