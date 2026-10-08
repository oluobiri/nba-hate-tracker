import type { ReactNode } from 'react'

/** A native details fold: what a reader looks up, never what a reader needs to believe a number. */
export function Fold({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="fold">
      <summary>{summary}</summary>
      <div className="fold__body">{children}</div>
    </details>
  )
}

/** A JSON value as the fold shows it: keys, strings and numbers in their own tones. */
export function JsonBlock({ value, note }: { value: unknown; note?: string }) {
  return (
    <pre className="json">
      {highlight(JSON.stringify(value, null, 2))}
      {note && (
        <>
          {'\n'}
          <span className="json__note">{note}</span>
        </>
      )}
    </pre>
  )
}

// One token per JSON lexeme: a string, a number, null, or punctuation.
const TOKEN = /"(?:[^"\\]|\\.)*"(\s*:)?|-?\d+(?:\.\d+)?|null|true|false/g

function highlight(json: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const m of json.matchAll(TOKEN)) {
    const at = m.index
    if (at > last) out.push(<span key={last} className="json__p">{json.slice(last, at)}</span>)
    const tok = m[0]
    if (m[1]) {
      out.push(<span key={`${at}k`} className="json__k">{tok.slice(0, tok.length - m[1].length)}</span>)
      out.push(<span key={`${at}c`} className="json__p">{m[1]}</span>)
    } else if (tok.startsWith('"')) out.push(<span key={at} className="json__s">{tok}</span>)
    else if (tok === 'null') out.push(<span key={at} className="json__null">{tok}</span>)
    else out.push(<span key={at} className="json__n">{tok}</span>)
    last = at + tok.length
  }
  if (last < json.length) out.push(<span key={last} className="json__p">{json.slice(last)}</span>)
  return out
}
