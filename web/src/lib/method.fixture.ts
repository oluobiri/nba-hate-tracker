// Row builders for the method tests: one method_examples row, every column
// defaulted, overrides on top. Test-only; nothing ships it.
import type { ClassifierIdentity, Corpus, MethodExamplesRow } from '../data/types.gen'

export const example = (o: Partial<MethodExamplesRow> = {}): MethodExamplesRow => ({
  slot: 'read',
  position: 1,
  comment_id: 'abc1234',
  link_id: 't3_xyz',
  body: 'Poole will probably have higher highs but Ajay feels more consistent',
  author_flair_text: ':okc-2: Thunder',
  score: 1,
  created_utc: 1778594789,
  mentioned_players: ['Ajay Mitchell', 'Jordan Poole'],
  mentioned_text: ['Ajay', 'Poole'],
  sentiment: 'pos',
  confidence: 0.7,
  sentiment_player: 'Ajay',
  attributed_player: 'Ajay Mitchell',
  player_id: 1,
  fan_team: 'Oklahoma City Thunder',
  attribution_case: 'several_resolved',
  target_raw: null,
  verified_target: null,
  label_sentiment: null,
  label_target: null,
  ...o,
})

export const corpus = (o: Partial<Corpus> = {}): Corpus => ({
  raw_comments: 1000,
  population_submitted: 400,
  classified: 399,
  usable: 390,
  attributed: 300,
  ...o,
})

export const classifier = (o: Partial<ClassifierIdentity> = {}): ClassifierIdentity => ({
  model: 'claude-haiku-4-5-20251001',
  prompt_version: 'v2',
  prompt: 'Classify.\n\nComment: {comment_body}\n\nRespond ONLY with JSON: {{"s":"pos|neg|neu"}}',
  max_tokens: 75,
  sampling_params: { temperature: 0 },
  ...o,
})
