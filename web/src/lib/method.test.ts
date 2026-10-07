import { describe, expect, it } from 'vitest'

import { answerOf, buildRequest, bySlot, caseRows, fillPrompt, gapDomain, gapRows, gapTicks, isQuotable, joinCopy, markNames, MethodCopyError, metricsPair, rawRecord, requireAccuracy, requireClassifier, requireTrace, rowRecord, shortModel, stageDrops, stageShare } from './method'
import { classifier, corpus, example } from './method.fixture'

describe('stageDrops', () => {
  it('is the difference of neighbouring corpus figures', () => {
    expect(stageDrops(corpus())).toEqual({ find: 600, answer: 10, pick: 90 })
  })

  it('refuses a corpus without the download figures', () => {
    expect(() => stageDrops(corpus({ raw_comments: null }))).toThrow(/raw_comments/)
  })

  it('shares a stage against the download, clamped', () => {
    expect(stageShare(400, 1000)).toBe(0.4)
    expect(stageShare(5, 0)).toBe(0)
    expect(stageShare(12, 10)).toBe(1)
  })
})

describe('markNames', () => {
  it('marks the first whole-word hit of each name, as the body spells it', () => {
    expect(markNames('Poole is fine but Ajay feels more consistent. Poole again.', ['Ajay', 'Poole'])).toEqual([
      { text: 'Poole', mark: true },
      { text: ' is fine but ', mark: false },
      { text: 'Ajay', mark: true },
      { text: ' feels more consistent. Poole again.', mark: false },
    ])
  })

  it('skips a hit inside a longer word and a name the body lacks', () => {
    expect(markNames('Lamelo and Ant are antsy', ['Ant', 'Wemby'])).toEqual([
      { text: 'Lamelo and ', mark: false },
      { text: 'Ant', mark: true },
      { text: ' are antsy', mark: false },
    ])
  })

  it('treats a name with punctuation or a space literally', () => {
    expect(markNames('Shai “Quick Andy’s Coming” Gilgeous-Alexander', ['Shai'])).toEqual([
      { text: 'Shai', mark: true },
      { text: ' “Quick Andy’s Coming” Gilgeous-Alexander', mark: false },
    ])
    expect(markNames('Lu Dort really is', ['Lu Dort'])).toEqual([
      { text: 'Lu Dort', mark: true },
      { text: ' really is', mark: false },
    ])
  })

  it('keeps the earlier of two overlapping hits and returns a body with no hit whole', () => {
    expect(markNames('Jaylen Brunson is a legend', ['Jaylen', 'Jaylen Brunson'])).toEqual([
      { text: 'Jaylen', mark: true },
      { text: ' Brunson is a legend', mark: false },
    ])
    expect(markNames('nothing here', ['Luka'])).toEqual([{ text: 'nothing here', mark: false }])
  })
})

describe('fillPrompt', () => {
  it('fills the slot and unescapes doubled braces, leaving braces in the value alone', () => {
    expect(fillPrompt('Comment: {comment_body}\n{{"s":"pos"}}', { comment_body: 'a {b} c' })).toBe('Comment: a {b} c\n{"s":"pos"}')
  })
})

describe('buildRequest', () => {
  it('rebuilds the request from the manifest block, the comment inside the prompt', () => {
    const req = buildRequest(example({ comment_id: 'oldhosi', body: 'Ajay is good' }), classifier())
    expect(req.custom_id).toBe('oldhosi')
    expect(Object.keys(req.params)).toEqual(['model', 'max_tokens', 'temperature', 'messages'])
    expect(req.params.messages).toEqual([{ role: 'user', content: 'Classify.\n\nComment: Ajay is good\n\nRespond ONLY with JSON: {"s":"pos|neg|neu"}' }])
  })

  it('refuses a classifier block without a prompt', () => {
    expect(() => buildRequest(example(), classifier({ prompt: null }))).toThrow(/no prompt/)
  })
})

describe('the answer and the records', () => {
  it('reads the three keys and the two record shapes without the author', () => {
    const row = example()
    expect(answerOf(row)).toEqual({ s: 'pos', c: 0.7, p: 'Ajay' })
    expect(Object.keys(rawRecord(row))).toEqual(['id', 'body', 'author_flair_text', 'score', 'link_id'])
    expect(Object.keys(rowRecord(row))).toEqual(['comment_id', 'mentioned_players', 'mentioned_text', 'sentiment', 'confidence', 'sentiment_player', 'attributed_player', 'fan_team', 'score'])
  })

  it('quotes only a sided answer at or above the floor', () => {
    expect(isQuotable(example({ sentiment: 'pos', confidence: 0.9 }), 0.9)).toBe(true)
    expect(isQuotable(example({ sentiment: 'pos', confidence: 0.85 }), 0.9)).toBe(false)
    expect(isQuotable(example({ sentiment: 'neu', confidence: 1 }), 0.9)).toBe(false)
  })
})

describe('slots', () => {
  const rows = [example({ slot: 'read', position: 2, comment_id: 'b' }), example({ slot: 'trace', position: 0, comment_id: 't' }), example({ slot: 'read', position: 1, comment_id: 'a' })]

  it('orders a slot by position and finds the one trace', () => {
    expect(bySlot(rows, 'read').map((r) => r.comment_id)).toEqual(['a', 'b'])
    expect(requireTrace(rows).comment_id).toBe('t')
  })

  it('refuses a table without exactly one trace', () => {
    expect(() => requireTrace(rows.slice(0, 1))).toThrow(/0 trace rows/)
    expect(() => requireTrace([...rows, example({ slot: 'trace' })])).toThrow(/2 trace rows/)
  })
})

const p = (name: string, neg: number, pos: number, total = 100) => ({ name, neg, pos, neu: total - neg - pos, total })

describe('metricsPair', () => {
  it('picks the two ranked players praised within tolerance whose negative rates are furthest apart, harsher first', () => {
    const rows = [p('a', 10, 30), p('b', 50, 30), p('c', 30, 31), p('d', 90, 60), p('thin', 95, 30, 10)]
    expect(metricsPair(rows, 50)!.map((r) => r.name)).toEqual(['b', 'a'])
  })

  it('is null when no two players are that close', () => {
    expect(metricsPair([p('a', 10, 30), p('b', 50, 50)], 50)).toBeNull()
  })
})

describe('the hand check gaps', () => {
  const mix = {
    neg: { classifier: 0.34, manual: 0.32, gap: 0.02, gap_margin: 0.05 },
    neu: { classifier: 0.37, manual: 0.32, gap: 0.05, gap_margin: 0.05 },
    pos: { classifier: 0.29, manual: 0.36, gap: -0.07, gap_margin: 0.06 },
  }

  it('reads the rows in sentiment order and calls a range that touches zero within', () => {
    expect(gapRows(mix)).toEqual([
      { cls: 'neg', gap: 0.02, margin: 0.05, call: 'within' },
      { cls: 'neu', gap: 0.05, margin: 0.05, call: 'within' },
      { cls: 'pos', gap: -0.07, margin: 0.06, call: 'outside' },
    ])
  })

  it('pads the widest range into a symmetric domain and keeps the ticks inside it', () => {
    const domain = gapDomain(gapRows(mix), 1)
    expect(domain).toEqual([-0.13, 0.13])
    expect(gapTicks(domain)).toEqual([-0.1, -0.05, 0, 0.05, 0.1])
    expect(gapTicks([-0.06, 0.06])).toEqual([-0.05, 0, 0.05])
  })

  it('fails on a block with a hole', () => {
    expect(() => gapRows(null)).toThrow(/class_mix/)
    expect(() => gapRows({ ...mix, neu: { ...mix.neu, gap: null } })).toThrow(/class_mix\.neu/)
    expect(() => gapRows({ neg: mix.neg, pos: mix.pos })).toThrow(/class_mix\.neu/)
  })
})

describe('shortModel', () => {
  it.each([
    ['claude-haiku-4-5-20251001', 'Haiku 4.5'],
    ['claude-sonnet-5', 'Sonnet 5'],
    ['claude-opus-4-1', 'Opus 4.1'],
    ['claude-3-5-haiku-20241022', '3.5 haiku'],
  ])('%s → %s', (id, short) => {
    expect(shortModel(id)).toBe(short)
  })
})

describe('joinCopy', () => {
  it('joins each key to its line', () => {
    expect([...joinCopy(['a', 'b'], { b: 'B', a: 'A' }, 'x').entries()]).toEqual([
      ['a', 'A'],
      ['b', 'B'],
    ])
  })

  it('names a row without copy and copy without a row', () => {
    expect(() => joinCopy(['a', 'b'], { a: 'A' }, 'method_examples')).toThrow(MethodCopyError)
    expect(() => joinCopy(['a', 'b'], { a: 'A' }, 'method_examples')).toThrow('method_examples: no copy for b')
    expect(() => joinCopy(['a'], { a: 'A', z: 'Z' }, 'method_examples')).toThrow('copy with no row: z')
  })
})

describe('caseRows', () => {
  it('orders the case rows and the trace by the table’s case order', () => {
    const rows = [
      example({ slot: 'case', position: 1, comment_id: 'u', attribution_case: 'several_unresolved' }),
      example({ slot: 'case', position: 2, comment_id: 'o', attribution_case: 'one_name' }),
      example({ slot: 'trace', position: 0, comment_id: 't', attribution_case: 'several_resolved' }),
      example({ slot: 'read', position: 1, comment_id: 'r', attribution_case: 'one_name' }),
    ]
    expect(caseRows(rows).map((r) => r.comment_id)).toEqual(['o', 't', 'u'])
  })

  it('refuses a case the table does not know', () => {
    const rows = [example({ slot: 'case', comment_id: 'q', attribution_case: 'mystery' }), example({ slot: 'trace' })]
    expect(() => caseRows(rows)).toThrow(/q has an unknown attribution_case mystery/)
  })
})

describe('the manifest blocks the page needs whole', () => {
  it('passes a filled classifier block and names a hole', () => {
    expect(requireClassifier({ sentiment: classifier() }, 'sentiment').prompt).toMatch(/^Classify/)
    expect(() => requireClassifier({}, 'sentiment')).toThrow('classifiers.sentiment: absent')
    expect(() => requireClassifier({ target: classifier({ max_tokens: null }) }, 'target')).toThrow('classifiers.target.max_tokens: null')
  })

  it('refuses an unlabeled accuracy block or one with a null figure', () => {
    const base = { labeled: true, drawn: 1, scored: 1, rejected: 0, seed: 1, drawn_at: 'd', rubric: 'v1', groups: {}, sentiment_agreement: 0.5, sentiment_margin: 0.1, target_agreement: 0.5, target_margin: 0.1, joint_agreement: 0.5, joint_margin: 0.1, by_class: {}, class_mix: {}, context_share: 0, unsure_share: 0, reject_share: 0 }
    expect(requireAccuracy(base).scored).toBe(1)
    expect(() => requireAccuracy({ ...base, labeled: false })).toThrow('not labeled')
    expect(() => requireAccuracy({ ...base, joint_margin: null })).toThrow('rules.accuracy.joint_margin: null')
  })
})
