import { Resvg } from '@resvg/resvg-js'
import { describe, expect, it } from 'vitest'

import { Frame } from './frame'
import { barSegments, type BoardCard, type PlayerCard, type TeamCard } from './model'
import { CARD_HEIGHT, CARD_WIDTH, pngSize, renderCard } from './render'

// Fixture images made by resvg: a red square and a red SVG logo.
const RED_PNG = `data:image/png;base64,${new Resvg('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect width="4" height="4" fill="#ff0000"/></svg>').render().asPng().toString('base64')}`
const RED_SVG = `data:image/svg+xml;base64,${Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><circle cx="2" cy="2" r="2" fill="#ff0000"/></svg>').toString('base64')}`

const counts = { neg: 51, neu: 43, pos: 6, total: 100 }
const base = { season: '2025-26', segments: barSegments(counts), stamp: null, image: RED_PNG }

const PLAYER: PlayerCard = { ...base, kind: 'player', name: 'Nickeil Alexander-Walker', eyebrow: 'MIN · G · #9', sentence: "r/NBA's 3rd most hated player.", nLine: 'n=100 comments about Nickeil Alexander-Walker' }
const UNOFFICIAL: PlayerCard = {
  ...PLAYER,
  stamp: 'unofficial',
  eyebrow: 'Free agent',
  sentence: 'Unofficial: 90 comments, 10 short of the official minimum of 100. Among all 223 tracked players he would rank 31st most hated.',
}
const TEAM: TeamCard = {
  ...base,
  kind: 'team',
  image: RED_SVG,
  title: 'Trail Blazers fans',
  eyebrow: 'POR · West',
  sentence: 'The 12th saltiest fanbase of 30: 51% of what Trail Blazers fans say about players is negative, 6% positive, across 100 comments.',
  nLine: 'n=100 comments by Trail Blazers fans about tracked players',
}
const BOARD: BoardCard = { ...base, kind: 'board', name: 'Draymond Green', kicker: '1,234,567 comments about 223 players', sentence: "r/NBA's most hated player is Draymond Green.", nLine: 'n=100 comments about Draymond Green' }

describe('Frame', () => {
  it.each([
    ['player', PLAYER],
    ['unofficial player', UNOFFICIAL],
    ['team', TEAM],
    ['board', BOARD],
  ])('renders a %s card at 1200 × 630', async (_kind, card) => {
    const png = await renderCard(Frame({ card, mark: RED_SVG, image: card.image }), card.kind === 'team' ? [] : [card.image])
    expect(pngSize(png)).toEqual({ width: CARD_WIDTH, height: CARD_HEIGHT })
  })
})
