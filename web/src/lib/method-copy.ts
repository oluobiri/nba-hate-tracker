// The lines the How it works page writes beside each example, keyed by the
// row they are about. The join in method.ts fails the build when a row has
// no line or a line has no row, so a change to the curated examples has to
// come through here. Bodies themselves are never copied: they are read from
// the table, verbatim.

/** One line per method_examples row, by comment_id: why this comment is on the page. */
export const EXAMPLE_COPY: Readonly<Record<string, string>> = {
  // trace
  oldhosi: 'Two names found; p picks one of them, as a nickname, and the name list resolves it.',
  // case
  nybof3j: 'One name found, and the classifier agrees.',
  o0sjgjm: 'One name always wins. The classifier blamed the front office; the rule counts it against the one player it found.',
  otq1na6: 'The classifier won’t say who it’s about, so the comment counts for no one.',
  npljrmh: 'Neither found name is the subject. “Year 23” is LeBron, and the classifier says so; he is tracked, so it counts for him.',
  orj7zfz: 'The commenter blended two names; p repeats the blend, and no list resolves it.',
  // read
  ooviaeg: 'Mockery in capitals, and a box-score line as the insult. The name is in capitals too and still matches.',
  oovib06: 'Admiration for a minimum-salary player. The answer names him by surname only, and the name list resolves it.',
  o1jce9x: 'Four words. “W” is the whole verdict, and “Hali” is one of Haliburton’s names.',
  odx8fa9: 'A statement of fact. Neutral, and the classifier names nobody; with one name in the comment it still counts for LeBron, as neutral. Neutral answers come back at 0.0 or 0.5 by habit.',
  nrep0bd: 'No insult word anywhere. The negative is the implication.',
  onpa94y: 'A mock nickname inside his real one. The classifier read it as neutral; a fan would call it a jab. That is the kind of miss the check by hand measures.',
  // slip
  nsxfnml: 'Quiet approval. “A good example of how players should deal with hecklers” is praise, read as neutral. The prompt never says what counts as positive.',
  oi9sy59: 'Sarcasm with no tell. The thread, where Dort has just tripped Booker, gives it away; the classifier only sees the comment.',
  novjx43: 'Two names. The comment prefers Booker; the classifier heard the knock on Cade and counted it against him. Both the label and the player differ.',
  // quote_check
  o3ksoqr: 'The scorn is for the trade, not for Luka. The verifier answers null: aimed at a decision, not a player.',
  oibjnzp: 'The praise is for Jaden McDaniels, who is not tracked; the only tracked name in the comment is Jokić, so the rule counts it for him. The verifier names McDaniels.',
}

/** The attribution cases as the table titles them. */
export const CASE_COPY: Readonly<Record<string, string>> = {
  one_name: 'One name',
  one_name_other_pick: 'One name, the classifier names someone else',
  several_resolved: 'Several names, the classifier names one',
  several_no_pick: 'Several names, no pick',
  several_resolved_unlisted: 'Several names, the pick is a tracked player not in the text',
  several_unresolved: 'Several names, the pick resolves to nobody',
}

/** The walkthrough's own line about its comment at the download step, keyed like the rest. */
export const TRACE_COPY: Readonly<Record<string, string>> = {
  oldhosi: 'A Thunder fan comparing two guards.',
}
