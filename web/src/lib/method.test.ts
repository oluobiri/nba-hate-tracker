import { describe, expect, it } from 'vitest'

import { answerOf, buildRequest, bySlot, fillPrompt, isQuotable, markNames, rawRecord, requireTrace, rowRecord, stageDrops, stageShare } from './method'
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
