import type { Answer as AnswerValue } from '../lib/method'

/** The classifier's whole reply as one mono chip: s in its sentiment colour, c, p or null. */
export function Answer({ s, c, p }: AnswerValue) {
  return (
    <code className="ans">
      <span className="ans__p">{'{'}</span>
      <span className="ans__k">"s"</span>
      <span className="ans__p">:</span>
      <span className={`ans__v v-${s}`}>"{s}"</span>
      <span className="ans__p">, </span>
      <span className="ans__k">"c"</span>
      <span className="ans__p">:</span>
      <span className="ans__v">{c}</span>
      <span className="ans__p">, </span>
      <span className="ans__k">"p"</span>
      <span className="ans__p">:</span>
      {p === null ? <span className="ans__null">null</span> : <span className="ans__v">"{p}"</span>}
      <span className="ans__p">{'}'}</span>
    </code>
  )
}
